import time
import numpy as np
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture
from sklearn.neighbors import LocalOutlierFactor
from sklearn.ensemble import IsolationForest
import matplotlib.pyplot as plt
from tqdm import tqdm

from ifcb import DataDirectory

from dataloader import IFCB_ASPECT_RATIO
from utilities import parallel_map

    
def plot_scores(scores):
    """
    Plot anomaly scores from a series of distributions.
    
    Parameters:
    scores: list of score dictionaries
    """
    anomaly_scores = [s['anomaly_score'] for s in scores]
    plt.hist(anomaly_scores, bins=20)
    plt.xlabel('Anomaly Score')
    plt.ylabel('Frequency')
    plt.show()


def extract_features(load_result, aspect_ratio = IFCB_ASPECT_RATIO):
    """Extract statistical features from a single point cloud distribution."""

    try:
        pid = load_result['pid']
        points = load_result['points']

        # some features won't converge or be useful if there are too few points
        if points.shape[0] < 30:  # 30 because 20 is the minimum for LOF
            raise ValueError("Distribution has too few points")

        # Normalize points to account for aspect ratio
        normalized_points = points.copy()
        normalized_points[:, 0] = normalized_points[:, 0] / aspect_ratio

        # Single component GMM features
        gmm = GaussianMixture(n_components=1, random_state=42)
        gmm.fit(normalized_points)
        
        means = gmm.means_[0]  # Single component mean
        covs = gmm.covariances_[0]  # Single component covariance
        
        # Basic stats on normalized points
        center = np.mean(normalized_points, axis=0)
        spread = np.std(normalized_points, axis=0)
        
        # LOF features on normalized points
        lof = LocalOutlierFactor(n_neighbors=20, novelty=True)
        lof.fit(normalized_points)
        lof_scores = -lof.negative_outlier_factor_
        
        # PCA features on normalized points
        pca = PCA(n_components=2)
        pca.fit(normalized_points)
        
        # First component angle (in radians)
        first_component = pca.components_[0]
        angle = np.arctan2(first_component[1], first_component[0])
        
        # Ratio of eigenvalues (indicates shape elongation)
        eigenvalue_ratio = pca.explained_variance_ratio_[0] / pca.explained_variance_ratio_[1]
        
        # Percent variance explained by first component
        variance_explained = pca.explained_variance_ratio_[0]
        
        # Combine all features
        features = np.concatenate([
            means.flatten(),  # 2 features
            covs.flatten(),   # 4 features (2x2 symmetric matrix)
            center,          # 2 features
            spread,          # 2 features
            [np.mean(lof_scores), np.std(lof_scores)],  # 2 features
            [angle, eigenvalue_ratio, variance_explained]  # 3 features
        ])
        
        return { 'pid': pid, 'features': features }
    
    except Exception as e:

        return { 'pid': pid, 'features': None }
    

def extract_features_parallel(load_results, aspect_ratio = IFCB_ASPECT_RATIO, n_jobs=-1):
    return parallel_map(
        extract_features,
        load_results,
        lambda x: (x, aspect_ratio),
        n_jobs=n_jobs
    )


def train_classifier(feature_results, contamination=0.1, n_jobs: int = -1):
    """
    Train a classifier using a list of feature results.
    
    Parameters:
    feature_results: list of feature dictionaries
    contamination: float, expected fraction of anomalous distributions
    """
    features = []
    for result in feature_results:
        if result['features'] is not None:
            features.append(result['features'])
    
    features = np.array(features)
    
    # Fit isolation forest to identify normal pattern at distribution level
    isolation_forest = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_jobs=n_jobs
    )
    isolation_forest.fit(features)
    
    return isolation_forest


def score_distributions(classifier, feature_results):
    """
    Score a series of distributions using a trained classifier.
    
    Parameters:
    classifier: trained IsolationForest instance
    load_results: list of load results
    """
    features = []
    pids = []
    bad_pids = []
    for result in feature_results:
        if result['features'] is not None:
            pids.append(result['pid'])
            features.append(result['features'])
        else:
            bad_pids.append(result['pid'])
    
    features = np.array(features)
    
    # Get anomaly scores from isolation forest
    anomaly_scores = [{
        'pid': pid,
        'anomaly_score': score
    } for pid, score in zip(pids, classifier.score_samples(features))]

    anomaly_scores.extend([{'pid': pid, 'anomaly_score': np.nan} for pid in bad_pids])
    
    return anomaly_scores
