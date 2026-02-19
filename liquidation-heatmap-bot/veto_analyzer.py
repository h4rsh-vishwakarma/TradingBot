"""
Veto Distribution Analyzer
Mines decision.jsonl to identify top blockers and suggest filter relaxations.
"""

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class VetoAnalyzer:
    """
    Analyzes veto reasons from decision logs to identify over-conservative filters.
    
    Purpose: Separate safety constraints (P0 - keep strict) from conservative 
    heuristics (P1/P2 - can relax) to increase trade frequency without risking capital.
    """
    
    def __init__(self, decision_log_path: str = 'logs/events/decision.jsonl'):
        self.decision_log_path = decision_log_path
        
        # P0 safety constraints (NEVER relax)
        self.p0_safety_vetoes = {
            'DAILY_CAP_HIT',
            'MAX_POSITIONS',
            'INVALID_R_SIZE',
            'INVALID_SL_SIDE',
            'ZERO_RISK_POSITION'
        }
        
        # P1 filters (can relax if too strict)
        self.p1_filters = {
            'EDGE_TOO_SMALL',
            'EDGE_TOO_SMALL_LEGACY',
            'EDGE_CALIBRATION_EDGE_TOO_SMALL',
            'EDGE_CALIBRATION_NEGATIVE_EV',
            'TOO_CLOSE_TO_LONG_CLUSTER',
            'TOO_CLOSE_TO_SHORT_CLUSTER',
            'REGIME_EXTREME_VOLATILITY',
            'REGIME_COUNTER_STRONG_UPTREND',
            'REGIME_COUNTER_STRONG_DOWNTREND',
            'REGIME_CROWDED_LONG_FUNDING',
            'REGIME_CROWDED_SHORT_FUNDING'
        }
        
        logger.info(f"Veto analyzer initialized: {decision_log_path}")
    
    def load_decisions(self, hours: int = 24) -> List[Dict]:
        """Load decision events from last N hours"""
        if not os.path.exists(self.decision_log_path):
            logger.warning(f"Decision log not found: {self.decision_log_path}")
            return []
        
        decisions = []
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        try:
            with open(self.decision_log_path, 'r') as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        
                        # Parse timestamp
                        ts_str = event.get('timestamp', '')
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                            if ts.replace(tzinfo=None) >= cutoff_time:
                                decisions.append(event)
                    except Exception as e:
                        logger.debug(f"Skipping malformed line: {e}")
            
            logger.info(f"Loaded {len(decisions)} decisions from last {hours}h")
            return decisions
            
        except Exception as e:
            logger.error(f"Failed to load decisions: {e}")
            return []
    
    def analyze_veto_distribution(self, hours: int = 24) -> Dict:
        """
        Analyze veto reason distribution and classify by severity.
        
        Returns:
            Dict with veto counts, percentages, and recommendations
        """
        decisions = self.load_decisions(hours)
        
        if not decisions:
            return {
                'total_decisions': 0,
                'veto_count': 0,
                'place_count': 0,
                'veto_rate': 0.0,
                'p0_vetoes': {},
                'p1_vetoes': {},
                'unknown_vetoes': {},
                'recommendations': []
            }
        
        # Count decision actions
        total_decisions = len(decisions)
        veto_count = sum(1 for d in decisions if d.get('action') == 'VETO')
        place_count = sum(1 for d in decisions if d.get('action') == 'PLACE')
        
        # Collect all veto reasons
        all_veto_reasons = []
        for decision in decisions:
            if decision.get('action') == 'VETO':
                veto_reasons = decision.get('veto_reasons', [])
                if isinstance(veto_reasons, list):
                    all_veto_reasons.extend(veto_reasons)
                elif veto_reasons:  # Single string
                    all_veto_reasons.append(veto_reasons)
        
        # Count by reason
        veto_counter = Counter(all_veto_reasons)
        
        # Classify by severity
        p0_vetoes = {k: v for k, v in veto_counter.items() if k in self.p0_safety_vetoes}
        p1_vetoes = {k: v for k, v in veto_counter.items() if k in self.p1_filters}
        unknown_vetoes = {k: v for k, v in veto_counter.items() 
                         if k not in self.p0_safety_vetoes and k not in self.p1_filters}
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            veto_counter, veto_count, place_count, total_decisions
        )
        
        return {
            'total_decisions': total_decisions,
            'veto_count': veto_count,
            'place_count': place_count,
            'veto_rate': veto_count / total_decisions if total_decisions > 0 else 0.0,
            'p0_vetoes': dict(p0_vetoes),
            'p1_vetoes': dict(p1_vetoes),
            'unknown_vetoes': dict(unknown_vetoes),
            'top_vetoes': veto_counter.most_common(10),
            'recommendations': recommendations
        }
    
    def _generate_recommendations(self, veto_counter: Counter, veto_count: int, 
                                 place_count: int, total_decisions: int) -> List[str]:
        """Generate actionable recommendations based on veto distribution"""
        recommendations = []
        
        # Overall veto rate check
        veto_rate = veto_count / total_decisions if total_decisions > 0 else 0.0
        place_rate = place_count / total_decisions if total_decisions > 0 else 0.0
        
        if veto_rate > 0.95:
            recommendations.append(
                f"⚠️ CRITICAL: {veto_rate*100:.1f}% veto rate (target: 80-90%). "
                "Filters are too strict - bot is not trading."
            )
        elif veto_rate > 0.90:
            recommendations.append(
                f"⚠️ HIGH: {veto_rate*100:.1f}% veto rate. Consider relaxing P1 filters."
            )
        
        if place_rate < 0.05:
            recommendations.append(
                f"⚠️ Low trade frequency: Only {place_rate*100:.1f}% PLACE actions. "
                "Target: 10-20%."
            )
        
        # Top veto reason analysis
        if veto_counter:
            top_veto, top_count = veto_counter.most_common(1)[0]
            top_pct = top_count / veto_count if veto_count > 0 else 0.0
            
            if top_pct > 0.5:
                recommendations.append(
                    f"🎯 TOP BLOCKER: '{top_veto}' ({top_pct*100:.1f}% of vetoes). "
                    f"Recommendation: {self._get_veto_recommendation(top_veto)}"
                )
            
            # Second blocker
            if len(veto_counter) > 1:
                second_veto, second_count = veto_counter.most_common(2)[1]
                second_pct = second_count / veto_count if veto_count > 0 else 0.0
                
                if second_pct > 0.3:
                    recommendations.append(
                        f"🎯 SECOND BLOCKER: '{second_veto}' ({second_pct*100:.1f}%). "
                        f"Recommendation: {self._get_veto_recommendation(second_veto)}"
                    )
        
        # P0 safety check
        p0_count = sum(count for reason, count in veto_counter.items() 
                      if reason in self.p0_safety_vetoes)
        if p0_count > veto_count * 0.1:
            recommendations.append(
                f"⚠️ P0 SAFETY VETOES: {p0_count} ({p0_count/veto_count*100:.1f}%). "
                "DO NOT relax - these protect capital. Check risk sizing or market conditions."
            )
        
        return recommendations
    
    def _get_veto_recommendation(self, veto_reason: str) -> str:
        """Get specific recommendation for a veto reason"""
        recommendations_map = {
            'EDGE_TOO_SMALL': 'Reduce min_edge_bps from 3 to 2 BPS',
            'EDGE_TOO_SMALL_LEGACY': 'Reduce min_edge_bps from 3 to 2 BPS',
            'EDGE_CALIBRATION_EDGE_TOO_SMALL': 'Reduce no_trade_band_bps from 15 to 10 BPS',
            'EDGE_CALIBRATION_NEGATIVE_EV': 'Check edge calibration fit quality (R² should be >0.3)',
            'TOO_CLOSE_TO_LONG_CLUSTER': 'Increase cluster distance threshold from 20 to 30 BPS',
            'TOO_CLOSE_TO_SHORT_CLUSTER': 'Increase cluster distance threshold from 20 to 30 BPS',
            'REGIME_EXTREME_VOLATILITY': 'Relax volatility Z-score threshold from 2.0 to 2.5',
            'REGIME_COUNTER_STRONG_UPTREND': 'Allow weak counter-trend (change strong threshold from 0.15 to 0.20)',
            'REGIME_COUNTER_STRONG_DOWNTREND': 'Allow weak counter-trend (change strong threshold from 0.15 to 0.20)',
            'REGIME_CROWDED_LONG_FUNDING': 'Increase funding threshold from 50% APR to 75% APR',
            'REGIME_CROWDED_SHORT_FUNDING': 'Increase funding threshold from -50% APR to -75% APR',
            'DAILY_CAP_HIT': 'DO NOT RELAX - P0 safety constraint. Check if cap too low for strategy.',
            'MAX_POSITIONS': 'DO NOT RELAX - P0 safety constraint. Check position holding time.',
        }
        
        return recommendations_map.get(veto_reason, 'Unknown veto - review decision logs manually')
    
    def print_report(self, hours: int = 24):
        """Print formatted analysis report"""
        analysis = self.analyze_veto_distribution(hours)
        
        print("\n" + "="*80)
        print(f"📊 VETO ANALYSIS REPORT (Last {hours}h)")
        print("="*80)
        
        print(f"\n📈 DECISION SUMMARY:")
        print(f"  Total Decisions: {analysis['total_decisions']}")
        print(f"  Vetoes: {analysis['veto_count']} ({analysis['veto_rate']*100:.1f}%)")
        print(f"  Placed: {analysis['place_count']} ({analysis['place_count']/max(1, analysis['total_decisions'])*100:.1f}%)")
        
        if analysis['top_vetoes']:
            print(f"\n🚫 TOP VETO REASONS:")
            for reason, count in analysis['top_vetoes'][:5]:
                pct = count / max(1, analysis['veto_count']) * 100
                severity = "P0" if reason in self.p0_safety_vetoes else "P1"
                print(f"  [{severity}] {reason}: {count} ({pct:.1f}%)")
        
        if analysis['p0_vetoes']:
            print(f"\n🛡️ P0 SAFETY VETOES (DO NOT RELAX):")
            for reason, count in sorted(analysis['p0_vetoes'].items(), key=lambda x: x[1], reverse=True):
                print(f"  {reason}: {count}")
        
        if analysis['p1_vetoes']:
            print(f"\n⚙️ P1 FILTER VETOES (CAN RELAX):")
            for reason, count in sorted(analysis['p1_vetoes'].items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"  {reason}: {count}")
        
        if analysis['recommendations']:
            print(f"\n💡 RECOMMENDATIONS:")
            for i, rec in enumerate(analysis['recommendations'], 1):
                print(f"  {i}. {rec}")
        
        print("\n" + "="*80 + "\n")


def test_veto_analyzer():
    """Test veto analyzer with sample data"""
    # Create sample decision log
    import tempfile
    import json
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        # Sample decisions
        decisions = [
            {'timestamp': datetime.utcnow().isoformat() + 'Z', 'action': 'VETO', 'veto_reasons': ['EDGE_TOO_SMALL']},
            {'timestamp': datetime.utcnow().isoformat() + 'Z', 'action': 'VETO', 'veto_reasons': ['EDGE_TOO_SMALL']},
            {'timestamp': datetime.utcnow().isoformat() + 'Z', 'action': 'VETO', 'veto_reasons': ['REGIME_EXTREME_VOLATILITY']},
            {'timestamp': datetime.utcnow().isoformat() + 'Z', 'action': 'PLACE'},
            {'timestamp': datetime.utcnow().isoformat() + 'Z', 'action': 'VETO', 'veto_reasons': ['DAILY_CAP_HIT']},
        ]
        
        for d in decisions:
            f.write(json.dumps(d) + '\n')
        
        temp_path = f.name
    
    # Test analyzer
    analyzer = VetoAnalyzer(temp_path)
    analyzer.print_report(24)
    
    # Cleanup
    os.unlink(temp_path)
    
    print("✅ Veto analyzer tests passed")


if __name__ == "__main__":
    test_veto_analyzer()
