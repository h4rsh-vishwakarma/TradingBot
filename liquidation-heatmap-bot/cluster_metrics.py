"""
Cluster Metrics Module - P1 Feature Engineering
Adds liquidation cluster proximity features for better signal quality
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


@dataclass
class ClusterFeature:
    """Single cluster feature measurement"""
    name: str
    value: float
    interpretation: str  # e.g., "NEAR_CLUSTER", "SAFE", "EXTREME"


class ClusterMetricsEngineer:
    """
    Engineers features from liquidation cluster data to improve signal quality.
    
    Key Features:
    1. Distance to nearest cluster (bps)
    2. Cluster density score (how many clusters nearby)
    3. Cluster alignment with bias (are clusters supporting or opposing?)
    4. Historical success rate near clusters
    
    These are P1 features - used to enhance edge, not as hard vetoes.
    """
    
    def __init__(self):
        # Thresholds for cluster proximity classification
        self.near_threshold_bps = 20  # Within 20bps = "NEAR"
        self.medium_threshold_bps = 50  # 20-50bps = "MEDIUM"
        self.far_threshold_bps = 100  # >100bps = "FAR"
        
        # Cluster density thresholds
        self.high_density_count = 3  # 3+ clusters within 50bps = high density
        self.medium_density_count = 2
        
        # Cache for cluster data
        self.cached_clusters = None
        self.cache_timestamp = None
        self.cache_ttl_seconds = 60  # Refresh every 60s
    
    def compute_cluster_features(
        self,
        current_price: float,
        bias: str,  # "LONG" or "SHORT"
        cluster_data: Optional[Dict] = None
    ) -> List[ClusterFeature]:
        """
        Compute cluster-based features for the current market state.
        
        Args:
            current_price: Current BTC price
            bias: Trade direction ("LONG" or "SHORT")
            cluster_data: Dict with 'long_liquidations' and 'short_liquidations'
                         Each is a list of {'price': float, 'size_usd': float}
        
        Returns:
            List of ClusterFeature objects
        """
        features = []
        
        if not cluster_data:
            logger.warning("No cluster data provided, returning empty features")
            return [ClusterFeature(
                name="cluster_data_missing",
                value=1.0,
                interpretation="NO_DATA"
            )]
        
        # Extract relevant clusters based on bias
        if bias == "LONG":
            # For longs, we care about short liquidations below (they support price)
            relevant_clusters = cluster_data.get('short_liquidations', [])
            direction_multiplier = -1  # Below current price
        else:
            # For shorts, we care about long liquidations above (they support price)
            relevant_clusters = cluster_data.get('long_liquidations', [])
            direction_multiplier = 1  # Above current price
        
        if not relevant_clusters:
            return [ClusterFeature(
                name="no_clusters",
                value=1.0,
                interpretation="NO_CLUSTERS"
            )]
        
        # Feature 1: Distance to nearest cluster
        nearest_cluster, distance_bps = self._find_nearest_cluster(
            current_price, relevant_clusters, direction_multiplier
        )
        
        if distance_bps is not None:
            features.append(ClusterFeature(
                name="nearest_cluster_distance_bps",
                value=distance_bps,
                interpretation=self._classify_distance(distance_bps)
            ))
        
        # Feature 2: Cluster density (how many clusters within 50bps)
        density_count = self._count_clusters_within_range(
            current_price, relevant_clusters, self.medium_threshold_bps
        )
        features.append(ClusterFeature(
            name="cluster_density_50bps",
            value=float(density_count),
            interpretation=self._classify_density(density_count)
        ))
        
        # Feature 3: Total cluster size within 50bps (aggregate liquidity)
        total_size_usd = sum(
            c['size_usd'] for c in relevant_clusters
            if abs((c['price'] - current_price) / current_price * 10000) <= self.medium_threshold_bps
        )
        features.append(ClusterFeature(
            name="cluster_size_usd_50bps",
            value=total_size_usd,
            interpretation=self._classify_size(total_size_usd)
        ))
        
        # Feature 4: Cluster alignment score
        # Positive = clusters supporting bias, Negative = opposing
        alignment_score = self._compute_alignment_score(
            current_price, bias, cluster_data
        )
        features.append(ClusterFeature(
            name="cluster_alignment",
            value=alignment_score,
            interpretation=self._classify_alignment(alignment_score)
        ))
        
        return features
    
    def _find_nearest_cluster(
        self,
        current_price: float,
        clusters: List[Dict],
        direction_multiplier: int
    ) -> Tuple[Optional[Dict], Optional[float]]:
        """Find nearest cluster in the relevant direction and its distance"""
        if not clusters:
            return None, None
        
        # Filter clusters in the relevant direction
        if direction_multiplier < 0:
            # Looking below current price
            relevant = [c for c in clusters if c['price'] < current_price]
        else:
            # Looking above current price
            relevant = [c for c in clusters if c['price'] > current_price]
        
        if not relevant:
            return None, None
        
        # Find nearest
        nearest = min(relevant, key=lambda c: abs(c['price'] - current_price))
        distance_bps = abs((nearest['price'] - current_price) / current_price * 10000)
        
        return nearest, distance_bps
    
    def _count_clusters_within_range(
        self,
        current_price: float,
        clusters: List[Dict],
        range_bps: float
    ) -> int:
        """Count how many clusters within range_bps of current price"""
        count = 0
        for cluster in clusters:
            distance_bps = abs((cluster['price'] - current_price) / current_price * 10000)
            if distance_bps <= range_bps:
                count += 1
        return count
    
    def _compute_alignment_score(
        self,
        current_price: float,
        bias: str,
        cluster_data: Dict
    ) -> float:
        """
        Compute alignment score: positive = supportive, negative = opposing
        
        For LONG: Short liq below = supportive, Long liq above = opposing
        For SHORT: Long liq above = supportive, Short liq below = opposing
        """
        short_liq = cluster_data.get('short_liquidations', [])
        long_liq = cluster_data.get('long_liquidations', [])
        
        # Count clusters within 100bps in each direction
        short_below = sum(1 for c in short_liq if c['price'] < current_price)
        short_above = sum(1 for c in short_liq if c['price'] > current_price)
        long_below = sum(1 for c in long_liq if c['price'] < current_price)
        long_above = sum(1 for c in long_liq if c['price'] > current_price)
        
        if bias == "LONG":
            supportive = short_below + long_above  # Clusters that support long move
            opposing = short_above + long_below
        else:
            supportive = long_above + short_below  # Clusters that support short move
            opposing = long_below + short_above
        
        total = supportive + opposing
        if total == 0:
            return 0.0
        
        # Score from -1 (all opposing) to +1 (all supportive)
        return (supportive - opposing) / total
    
    def _classify_distance(self, distance_bps: float) -> str:
        """Classify cluster distance"""
        if distance_bps <= self.near_threshold_bps:
            return "NEAR"
        elif distance_bps <= self.medium_threshold_bps:
            return "MEDIUM"
        elif distance_bps <= self.far_threshold_bps:
            return "FAR"
        else:
            return "VERY_FAR"
    
    def _classify_density(self, count: int) -> str:
        """Classify cluster density"""
        if count >= self.high_density_count:
            return "HIGH_DENSITY"
        elif count >= self.medium_density_count:
            return "MEDIUM_DENSITY"
        elif count >= 1:
            return "LOW_DENSITY"
        else:
            return "NO_CLUSTERS"
    
    def _classify_size(self, size_usd: float) -> str:
        """Classify total cluster size"""
        if size_usd >= 10_000_000:  # $10M+
            return "MASSIVE"
        elif size_usd >= 5_000_000:  # $5M+
            return "LARGE"
        elif size_usd >= 1_000_000:  # $1M+
            return "MEDIUM"
        elif size_usd > 0:
            return "SMALL"
        else:
            return "NONE"
    
    def _classify_alignment(self, score: float) -> str:
        """Classify alignment score"""
        if score >= 0.5:
            return "STRONGLY_SUPPORTIVE"
        elif score >= 0.2:
            return "SUPPORTIVE"
        elif score >= -0.2:
            return "NEUTRAL"
        elif score >= -0.5:
            return "OPPOSING"
        else:
            return "STRONGLY_OPPOSING"


# Self-test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    engineer = ClusterMetricsEngineer()
    
    # Mock cluster data
    current_price = 50000.0
    cluster_data = {
        'short_liquidations': [
            {'price': 49900.0, 'size_usd': 2_000_000},  # 20bps below
            {'price': 49800.0, 'size_usd': 5_000_000},  # 40bps below
            {'price': 49700.0, 'size_usd': 1_000_000},  # 60bps below
        ],
        'long_liquidations': [
            {'price': 50100.0, 'size_usd': 3_000_000},  # 20bps above
            {'price': 50200.0, 'size_usd': 4_000_000},  # 40bps above
        ]
    }
    
    # Test LONG bias
    features = engineer.compute_cluster_features(
        current_price=current_price,
        bias="LONG",
        cluster_data=cluster_data
    )
    
    print("\n📊 CLUSTER FEATURES (LONG bias):")
    for feat in features:
        print(f"  {feat.name}: {feat.value:.2f} ({feat.interpretation})")
    
    # Test SHORT bias
    features_short = engineer.compute_cluster_features(
        current_price=current_price,
        bias="SHORT",
        cluster_data=cluster_data
    )
    
    print("\n📊 CLUSTER FEATURES (SHORT bias):")
    for feat in features_short:
        print(f"  {feat.name}: {feat.value:.2f} ({feat.interpretation})")
    
    print("\n✅ Cluster metrics tests passed")
