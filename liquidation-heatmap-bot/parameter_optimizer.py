"""
Automated Parameter Optimization Engine
========================================
Inspired by TradingView Auto Backtest & Optimize Engine
Implements genetic algorithm and random sampling for efficient parameter discovery.

Features:
- Random sampling of parameter space (10-20% testing vs full grid)
- Genetic algorithm for refinement
- Multi-objective optimization (Score based on Sharpe, PF, WR, DD)
- Regime-adaptive parameter selection
- Real-time optimization during paper trading
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
import json
import logging
from datetime import datetime
from pathlib import Path
import random
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class ParameterSet:
    """Individual parameter configuration"""
    id: str
    sl_type: str  # 'fixed', 'atr', 'trailing', 'chandelier', 'ma', 'sar'
    sl_pct: Optional[float] = None
    sl_atr_mult: Optional[float] = None
    sl_period: Optional[int] = None
    tp_type: str = 'rr'  # 'rr' (risk/reward), 'fixed', 'atr'
    tp_rr: Optional[float] = None
    tp_pct: Optional[float] = None
    tp_atr_mult: Optional[float] = None
    size_usd: float = 1000
    regime: Optional[str] = None  # 'trending', 'ranging', 'volatile', 'any'
    
    # Performance metrics (filled after backtest)
    score: float = 0.0
    total_pnl: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    generation: int = 0
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OptimizationResult:
    """Results from optimization run"""
    best_params: ParameterSet
    all_results: List[ParameterSet]
    generations: int
    total_tested: int
    best_score: float
    optimization_time: float


class LinearCongruentialGenerator:
    """
    LCG for pseudo-random generation with prime number enhancement.
    Ensures unique, well-distributed parameter combinations.
    """
    
    def __init__(self, seed: int = None):
        self.seed = seed or int(datetime.now().timestamp())
        # Use prime numbers for better distribution
        self.a = 1103515245  # Multiplier (prime-based)
        self.c = 12345       # Increment
        self.m = 2**31       # Modulus
        self.current = self.seed
        
    def next(self) -> int:
        """Generate next random number"""
        self.current = (self.a * self.current + self.c) % self.m
        return self.current
    
    def uniform(self, low: float, high: float) -> float:
        """Generate uniform random float in [low, high]"""
        return low + (high - low) * (self.next() / self.m)
    
    def choice(self, options: List[Any]) -> Any:
        """Choose random element from list"""
        idx = int(self.uniform(0, len(options)))
        return options[min(idx, len(options) - 1)]


class ParameterOptimizer:
    """
    Main optimization engine using random sampling + genetic algorithm.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.lcg = LinearCongruentialGenerator()
        self.population_size = config.get('population_size', 300)
        self.generations = config.get('max_generations', 10)
        self.elite_size = config.get('elite_size', 30)
        self.mutation_rate = config.get('mutation_rate', 0.2)
        
        # Parameter ranges
        self.param_ranges = self._initialize_ranges()
        
        # Results storage
        self.all_tested: List[ParameterSet] = []
        self.generation_best: List[ParameterSet] = []
        
    def _initialize_ranges(self) -> Dict[str, Any]:
        """Define parameter search space"""
        return {
            'sl_types': ['fixed', 'atr', 'trailing', 'chandelier', 'ma'],
            'sl_pct_range': (0.005, 0.025, 0.001),  # min, max, step
            'sl_atr_mult_range': (1.0, 3.0, 0.25),
            'sl_period_range': (10, 50, 5),
            'tp_types': ['rr', 'fixed', 'atr'],
            'tp_rr_range': (1.0, 4.0, 0.1),
            'tp_pct_range': (0.01, 0.05, 0.005),
            'tp_atr_mult_range': (1.5, 4.0, 0.25),
            'size_usd_range': (500, 2000, 100),
            'regimes': ['any', 'trending', 'ranging', 'volatile']
        }
    
    def generate_random_population(self, size: int = None) -> List[ParameterSet]:
        """
        Generate random parameter sets using LCG.
        Ensures unique, well-distributed combinations.
        """
        size = size or self.population_size
        population = []
        
        for i in range(size):
            param_id = f"gen0_id{i:04d}"
            
            # Random SL type
            sl_type = self.lcg.choice(self.param_ranges['sl_types'])
            
            # Generate SL parameters based on type
            sl_pct = None
            sl_atr_mult = None
            sl_period = None
            
            if sl_type == 'fixed':
                sl_min, sl_max, sl_step = self.param_ranges['sl_pct_range']
                sl_pct = self._round_to_step(
                    self.lcg.uniform(sl_min, sl_max), sl_step
                )
            elif sl_type in ['atr', 'chandelier']:
                mult_min, mult_max, mult_step = self.param_ranges['sl_atr_mult_range']
                sl_atr_mult = self._round_to_step(
                    self.lcg.uniform(mult_min, mult_max), mult_step
                )
                per_min, per_max, per_step = self.param_ranges['sl_period_range']
                sl_period = int(self._round_to_step(
                    self.lcg.uniform(per_min, per_max), per_step
                ))
            elif sl_type in ['trailing', 'ma']:
                sl_min, sl_max, sl_step = self.param_ranges['sl_pct_range']
                sl_pct = self._round_to_step(
                    self.lcg.uniform(sl_min, sl_max), sl_step
                )
                per_min, per_max, per_step = self.param_ranges['sl_period_range']
                sl_period = int(self._round_to_step(
                    self.lcg.uniform(per_min, per_max), per_step
                ))
            
            # Random TP type
            tp_type = self.lcg.choice(self.param_ranges['tp_types'])
            
            # Generate TP parameters
            tp_rr = None
            tp_pct = None
            tp_atr_mult = None
            
            if tp_type == 'rr':
                rr_min, rr_max, rr_step = self.param_ranges['tp_rr_range']
                tp_rr = self._round_to_step(
                    self.lcg.uniform(rr_min, rr_max), rr_step
                )
            elif tp_type == 'fixed':
                tp_min, tp_max, tp_step = self.param_ranges['tp_pct_range']
                tp_pct = self._round_to_step(
                    self.lcg.uniform(tp_min, tp_max), tp_step
                )
            elif tp_type == 'atr':
                mult_min, mult_max, mult_step = self.param_ranges['tp_atr_mult_range']
                tp_atr_mult = self._round_to_step(
                    self.lcg.uniform(mult_min, mult_max), mult_step
                )
            
            # Random position size
            size_min, size_max, size_step = self.param_ranges['size_usd_range']
            size_usd = self._round_to_step(
                self.lcg.uniform(size_min, size_max), size_step
            )
            
            # Random regime
            regime = self.lcg.choice(self.param_ranges['regimes'])
            
            params = ParameterSet(
                id=param_id,
                sl_type=sl_type,
                sl_pct=sl_pct,
                sl_atr_mult=sl_atr_mult,
                sl_period=sl_period,
                tp_type=tp_type,
                tp_rr=tp_rr,
                tp_pct=tp_pct,
                tp_atr_mult=tp_atr_mult,
                size_usd=size_usd,
                regime=regime,
                generation=0
            )
            
            population.append(params)
        
        return population
    
    def _round_to_step(self, value: float, step: float) -> float:
        """Round value to nearest step"""
        return round(value / step) * step
    
    def calculate_score(self, params: ParameterSet) -> float:
        """
        Calculate comprehensive score based on multiple metrics.
        Similar to TradingView engine's multi-factor scoring.
        """
        if params.total_trades < 10:
            return 0.0
        
        # Weighted components (randomized for diversity)
        weights = {
            'profit': self.lcg.uniform(0.15, 0.25),
            'win_rate': self.lcg.uniform(0.10, 0.20),
            'profit_factor': self.lcg.uniform(0.15, 0.25),
            'sharpe': self.lcg.uniform(0.15, 0.25),
            'drawdown': self.lcg.uniform(0.10, 0.20),
            'trade_count': self.lcg.uniform(0.05, 0.10)
        }
        
        # Normalize weights
        total = sum(weights.values())
        weights = {k: v/total for k, v in weights.items()}
        
        # Calculate normalized scores (0-1 range)
        profit_score = self._normalize_score(params.total_pnl, -100, 500)
        wr_score = self._normalize_score(params.win_rate, 0, 100)
        pf_score = self._normalize_score(params.profit_factor, 0, 3)
        sharpe_score = self._normalize_score(params.sharpe_ratio, -1, 3)
        dd_score = self._normalize_score(100 - params.max_drawdown, 80, 100)  # Invert
        trade_score = self._normalize_score(params.total_trades, 10, 100)
        
        # Weighted sum
        score = (
            weights['profit'] * profit_score +
            weights['win_rate'] * wr_score +
            weights['profit_factor'] * pf_score +
            weights['sharpe'] * sharpe_score +
            weights['drawdown'] * dd_score +
            weights['trade_count'] * trade_score
        )
        
        return score * 100  # Scale to 0-100
    
    def _normalize_score(self, value: float, min_val: float, max_val: float) -> float:
        """Normalize value to 0-1 range"""
        if value <= min_val:
            return 0.0
        if value >= max_val:
            return 1.0
        return (value - min_val) / (max_val - min_val)
    
    def crossover(self, parent1: ParameterSet, parent2: ParameterSet, 
                  gen: int) -> ParameterSet:
        """
        Genetic crossover: combine two parent parameter sets.
        """
        child_id = f"gen{gen}_cross_{random.randint(1000, 9999)}"
        
        # Randomly select parameters from parents
        child = ParameterSet(
            id=child_id,
            sl_type=random.choice([parent1.sl_type, parent2.sl_type]),
            sl_pct=random.choice([parent1.sl_pct, parent2.sl_pct]),
            sl_atr_mult=random.choice([parent1.sl_atr_mult, parent2.sl_atr_mult]),
            sl_period=random.choice([parent1.sl_period, parent2.sl_period]),
            tp_type=random.choice([parent1.tp_type, parent2.tp_type]),
            tp_rr=random.choice([parent1.tp_rr, parent2.tp_rr]),
            tp_pct=random.choice([parent1.tp_pct, parent2.tp_pct]),
            tp_atr_mult=random.choice([parent1.tp_atr_mult, parent2.tp_atr_mult]),
            size_usd=random.choice([parent1.size_usd, parent2.size_usd]),
            regime=random.choice([parent1.regime, parent2.regime]),
            generation=gen
        )
        
        return child
    
    def mutate(self, params: ParameterSet) -> ParameterSet:
        """
        Genetic mutation: randomly modify parameters.
        """
        if random.random() > self.mutation_rate:
            return params
        
        # Randomly mutate one parameter
        mutation_choice = random.choice([
            'sl_type', 'sl_value', 'tp_type', 'tp_value', 'size', 'regime'
        ])
        
        if mutation_choice == 'sl_type':
            params.sl_type = self.lcg.choice(self.param_ranges['sl_types'])
        elif mutation_choice == 'sl_value':
            if params.sl_type == 'fixed':
                sl_min, sl_max, sl_step = self.param_ranges['sl_pct_range']
                params.sl_pct = self._round_to_step(
                    self.lcg.uniform(sl_min, sl_max), sl_step
                )
        elif mutation_choice == 'tp_type':
            params.tp_type = self.lcg.choice(self.param_ranges['tp_types'])
        elif mutation_choice == 'tp_value':
            if params.tp_type == 'rr':
                rr_min, rr_max, rr_step = self.param_ranges['tp_rr_range']
                params.tp_rr = self._round_to_step(
                    self.lcg.uniform(rr_min, rr_max), rr_step
                )
        elif mutation_choice == 'size':
            size_min, size_max, size_step = self.param_ranges['size_usd_range']
            params.size_usd = self._round_to_step(
                self.lcg.uniform(size_min, size_max), size_step
            )
        elif mutation_choice == 'regime':
            params.regime = self.lcg.choice(self.param_ranges['regimes'])
        
        return params
    
    def evolve_generation(self, population: List[ParameterSet], 
                         gen: int) -> List[ParameterSet]:
        """
        Genetic algorithm: create next generation from current population.
        """
        # Sort by score (descending)
        sorted_pop = sorted(population, key=lambda p: p.score, reverse=True)
        
        # Select elites (top performers)
        elites = sorted_pop[:self.elite_size]
        
        # Generate offspring through crossover
        offspring = []
        while len(offspring) < self.population_size - self.elite_size:
            # Tournament selection
            parent1 = max(random.sample(sorted_pop[:50], 3), key=lambda p: p.score)
            parent2 = max(random.sample(sorted_pop[:50], 3), key=lambda p: p.score)
            
            # Crossover
            child = self.crossover(parent1, parent2, gen)
            
            # Mutation
            child = self.mutate(child)
            
            offspring.append(child)
        
        # Combine elites and offspring
        new_generation = elites + offspring
        
        return new_generation
    
    def optimize(self, backtest_func, save_results: bool = True) -> OptimizationResult:
        """
        Main optimization loop.
        
        Args:
            backtest_func: Function that takes ParameterSet and returns updated ParameterSet with metrics
            save_results: Whether to save results to file
        
        Returns:
            OptimizationResult with best parameters and all tested combinations
        """
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("STARTING PARAMETER OPTIMIZATION")
        logger.info(f"Population Size: {self.population_size}")
        logger.info(f"Generations: {self.generations}")
        logger.info("=" * 60)
        
        # Generate initial random population
        logger.info("Generating initial random population...")
        population = self.generate_random_population()
        
        best_overall = None
        
        for gen in range(self.generations):
            logger.info(f"\n{'='*60}")
            logger.info(f"GENERATION {gen + 1}/{self.generations}")
            logger.info(f"{'='*60}")
            
            # Evaluate population
            logger.info(f"Testing {len(population)} parameter combinations...")
            evaluated_pop = []
            
            for i, params in enumerate(population):
                if i % 50 == 0:
                    logger.info(f"  Progress: {i}/{len(population)} ({i/len(population)*100:.1f}%)")
                
                # Run backtest
                try:
                    result = backtest_func(params)
                    result.score = self.calculate_score(result)
                    evaluated_pop.append(result)
                    self.all_tested.append(result)
                except Exception as e:
                    logger.error(f"  Backtest failed for {params.id}: {e}")
                    continue
            
            # Find best in generation
            gen_best = max(evaluated_pop, key=lambda p: p.score)
            self.generation_best.append(gen_best)
            
            logger.info(f"\nGeneration {gen + 1} Best:")
            logger.info(f"  ID: {gen_best.id}")
            logger.info(f"  Score: {gen_best.score:.2f}")
            logger.info(f"  PnL: ${gen_best.total_pnl:.2f}")
            logger.info(f"  Win Rate: {gen_best.win_rate:.1f}%")
            logger.info(f"  Profit Factor: {gen_best.profit_factor:.2f}")
            logger.info(f"  Sharpe: {gen_best.sharpe_ratio:.2f}")
            logger.info(f"  Max DD: {gen_best.max_drawdown:.1f}%")
            logger.info(f"  SL: {gen_best.sl_type} | TP: {gen_best.tp_type} (R:R {gen_best.tp_rr})")
            
            # Track best overall
            if best_overall is None or gen_best.score > best_overall.score:
                best_overall = gen_best
                logger.info(f"  🏆 NEW BEST OVERALL!")
            
            # Evolve next generation (unless last generation)
            if gen < self.generations - 1:
                logger.info(f"\nEvolving generation {gen + 2}...")
                population = self.evolve_generation(evaluated_pop, gen + 1)
        
        end_time = datetime.now()
        optimization_time = (end_time - start_time).total_seconds()
        
        logger.info("\n" + "=" * 60)
        logger.info("OPTIMIZATION COMPLETE!")
        logger.info("=" * 60)
        logger.info(f"Time: {optimization_time:.1f} seconds")
        logger.info(f"Total Tested: {len(self.all_tested)}")
        logger.info(f"Best Score: {best_overall.score:.2f}")
        logger.info(f"Best Parameters: {best_overall.id}")
        
        result = OptimizationResult(
            best_params=best_overall,
            all_results=self.all_tested,
            generations=self.generations,
            total_tested=len(self.all_tested),
            best_score=best_overall.score,
            optimization_time=optimization_time
        )
        
        if save_results:
            self.save_results(result)
        
        return result
    
    def save_results(self, result: OptimizationResult):
        """Save optimization results to files"""
        output_dir = Path('optimization_results')
        output_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save best parameters
        best_file = output_dir / f'best_params_{timestamp}.json'
        with open(best_file, 'w') as f:
            json.dump(result.best_params.to_dict(), f, indent=2)
        
        # Save all results as CSV
        results_df = pd.DataFrame([p.to_dict() for p in result.all_results])
        results_df = results_df.sort_values('score', ascending=False)
        results_file = output_dir / f'all_results_{timestamp}.csv'
        results_df.to_csv(results_file, index=False)
        
        # Save generation progression
        gen_df = pd.DataFrame([p.to_dict() for p in self.generation_best])
        gen_file = output_dir / f'generation_best_{timestamp}.csv'
        gen_df.to_csv(gen_file, index=False)
        
        logger.info(f"\nResults saved to:")
        logger.info(f"  Best: {best_file}")
        logger.info(f"  All: {results_file}")
        logger.info(f"  Generations: {gen_file}")


def load_best_parameters(results_dir: str = 'optimization_results') -> Optional[ParameterSet]:
    """Load the most recent best parameters from optimization results"""
    results_path = Path(results_dir)
    if not results_path.exists():
        return None
    
    # Find most recent best_params file
    best_files = sorted(results_path.glob('best_params_*.json'))
    if not best_files:
        return None
    
    latest_file = best_files[-1]
    with open(latest_file, 'r') as f:
        data = json.load(f)
    
    return ParameterSet(**data)
