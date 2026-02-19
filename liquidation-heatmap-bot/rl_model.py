"""
Advanced Reinforcement Learning Module
Implements PPO-based RL agent with improved reward function and state management
"""

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.distributions import Normal
from collections import deque
import logging
import joblib
import os
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import random

logger = logging.getLogger(__name__)

@dataclass
class Experience:
    """Experience tuple for RL training"""
    state: np.ndarray
    action: float
    reward: float
    next_state: np.ndarray
    done: bool
    info: Dict

class PolicyNetwork(nn.Module):
    """Policy network for PPO agent"""
    
    def __init__(self, state_dim: int, hidden_dim: int = 256):
        super(PolicyNetwork, self).__init__()
        
        self.network = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1)
        )
        
        # Initialize weights
        self.apply(self._init_weights)
    
    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            torch.nn.init.xavier_uniform_(module.weight)
            torch.nn.init.constant_(module.bias, 0)
    
    def forward(self, state):
        return torch.tanh(self.network(state)) * 0.5 + 0.5  # Output between 0 and 1

class ValueNetwork(nn.Module):
    """Value network for PPO agent"""
    
    def __init__(self, state_dim: int, hidden_dim: int = 256):
        super(ValueNetwork, self).__init__()
        
        self.network = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1)
        )
        
        # Initialize weights
        self.apply(self._init_weights)
    
    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            torch.nn.init.xavier_uniform_(module.weight)
            torch.nn.init.constant_(module.bias, 0)
    
    def forward(self, state):
        return self.network(state)

class PPOMemory:
    """Memory buffer for PPO training"""
    
    def __init__(self, capacity: int = 10000):
        self.capacity = capacity
        self.buffer = deque(maxlen=capacity)
        self.states = []
        self.actions = []
        self.rewards = []
        self.next_states = []
        self.dones = []
        self.log_probs = []
        self.values = []
        self.advantages = []
        self.returns = []
    
    def push(self, experience: Experience, log_prob: float, value: float):
        """Add experience to buffer"""
        self.states.append(experience.state)
        self.actions.append(experience.action)
        self.rewards.append(experience.reward)
        self.next_states.append(experience.next_state)
        self.dones.append(experience.done)
        self.log_probs.append(log_prob)
        self.values.append(value)
    
    def compute_advantages_and_returns(self, gamma: float = 0.99, lam: float = 0.95):
        """Compute GAE advantages and returns"""
        advantages = []
        returns = []
        
        # Convert to numpy arrays
        rewards = np.array(self.rewards)
        values = np.array(self.values)
        dones = np.array(self.dones)
        
        # Compute advantages using GAE
        gae = 0
        for t in reversed(range(len(rewards))):
            if t == len(rewards) - 1:
                next_value = 0
            else:
                next_value = values[t + 1]
            
            delta = rewards[t] + gamma * next_value * (1 - dones[t]) - values[t]
            gae = delta + gamma * lam * (1 - dones[t]) * gae
            advantages.insert(0, gae)
            returns.insert(0, gae + values[t])
        
        self.advantages = advantages
        self.returns = returns
    
    def get_batch(self, batch_size: int):
        """Get random batch from buffer"""
        indices = random.sample(range(len(self.states)), min(batch_size, len(self.states)))
        
        return {
            'states': torch.FloatTensor([self.states[i] for i in indices]),
            'actions': torch.FloatTensor([self.actions[i] for i in indices]),
            'log_probs': torch.FloatTensor([self.log_probs[i] for i in indices]),
            'values': torch.FloatTensor([self.values[i] for i in indices]),
            'advantages': torch.FloatTensor([self.advantages[i] for i in indices]),
            'returns': torch.FloatTensor([self.returns[i] for i in indices])
        }
    
    def clear(self):
        """Clear the buffer"""
        self.states.clear()
        self.actions.clear()
        self.rewards.clear()
        self.next_states.clear()
        self.dones.clear()
        self.log_probs.clear()
        self.values.clear()
        self.advantages.clear()
        self.returns.clear()

class AdvancedRewardFunction:
    """Advanced reward function for trading RL agent"""
    
    def __init__(self, config):
        self.config = config
        self.trading_config = config.get_trading_config()
        
        # Reward components weights
        self.profit_weight = 1.0
        self.drawdown_weight = -2.0
        self.consistency_weight = 0.5
        self.risk_adjusted_weight = 1.5
        self.exploration_weight = 0.1
        
        # Performance tracking
        self.returns_history = deque(maxlen=100)
        self.drawdown_history = deque(maxlen=100)
        self.sharpe_history = deque(maxlen=50)
        
    def calculate_reward(self, trade_outcome: Dict, confidence: float, 
                        market_features: Dict) -> float:
        """Calculate comprehensive reward for trade outcome"""
        
        # Base profit/loss reward
        profit_reward = self._calculate_profit_reward(trade_outcome)
        
        # Drawdown penalty
        drawdown_penalty = self._calculate_drawdown_penalty(trade_outcome)
        
        # Consistency reward
        consistency_reward = self._calculate_consistency_reward(trade_outcome)
        
        # Risk-adjusted reward
        risk_adjusted_reward = self._calculate_risk_adjusted_reward(trade_outcome)
        
        # Exploration bonus
        exploration_bonus = self._calculate_exploration_bonus(confidence, market_features)
        
        # Market regime adaptation
        regime_bonus = self._calculate_regime_bonus(trade_outcome, market_features)
        
        # Combine all components
        total_reward = (
            self.profit_weight * profit_reward +
            self.drawdown_weight * drawdown_penalty +
            self.consistency_weight * consistency_reward +
            self.risk_adjusted_weight * risk_adjusted_reward +
            self.exploration_weight * exploration_bonus +
            regime_bonus
        )
        
        # Update performance tracking
        self._update_performance_tracking(trade_outcome)
        
        return total_reward
    
    def _calculate_profit_reward(self, trade_outcome: Dict) -> float:
        """Calculate profit-based reward"""
        if trade_outcome.get('is_profitable', False):
            rr_achieved = trade_outcome.get('rr_achieved', 1.0)
            # Logarithmic scaling for diminishing returns
            return np.log(1 + rr_achieved)
        else:
            # Penalty for losses
            loss_ratio = abs(trade_outcome.get('loss_ratio', 1.0))
            return -np.log(1 + loss_ratio)
    
    def _calculate_drawdown_penalty(self, trade_outcome: Dict) -> float:
        """Calculate drawdown penalty"""
        current_drawdown = trade_outcome.get('current_drawdown', 0)
        max_drawdown = self.trading_config.max_drawdown
        
        if current_drawdown > max_drawdown:
            # Severe penalty for exceeding max drawdown
            return -10.0
        elif current_drawdown > max_drawdown * 0.8:
            # Warning penalty
            return -2.0
        else:
            # Small penalty proportional to drawdown
            return -current_drawdown * 2
    
    def _calculate_consistency_reward(self, trade_outcome: Dict) -> float:
        """Calculate consistency reward"""
        if len(self.returns_history) < 10:
            return 0
        
        recent_returns = list(self.returns_history)[-10:]
        win_rate = sum(1 for r in recent_returns if r > 0) / len(recent_returns)
        
        # Reward high win rates
        if win_rate > 0.7:
            return 1.0
        elif win_rate > 0.6:
            return 0.5
        elif win_rate < 0.4:
            return -0.5
        else:
            return 0
    
    def _calculate_risk_adjusted_reward(self, trade_outcome: Dict) -> float:
        """Calculate risk-adjusted reward (Sharpe ratio component)"""
        if len(self.returns_history) < 20:
            return 0
        
        recent_returns = list(self.returns_history)[-20:]
        mean_return = np.mean(recent_returns)
        std_return = np.std(recent_returns)
        
        if std_return > 0:
            sharpe_ratio = mean_return / std_return
            # Reward positive Sharpe ratios
            return max(0.0, float(sharpe_ratio * 0.5))
        else:
            return 0.0
    
    def _calculate_exploration_bonus(self, confidence: float, market_features: Dict) -> float:
        """Calculate exploration bonus for novel situations"""
        # Bonus for moderate confidence (not too high/low)
        if 0.4 <= confidence <= 0.7:
            return 0.1
        
        # Penalty for overconfidence
        if confidence > 0.9:
            return -0.2
        
        return 0
    
    def _calculate_regime_bonus(self, trade_outcome: Dict, market_features: Dict) -> float:
        """Calculate bonus for adapting to market regimes"""
        vol_regime = market_features.get('vol_regime', 0)
        
        # Bonus for successful trades in high volatility
        if vol_regime == 1 and trade_outcome.get('is_profitable', False):
            return 0.3
        
        # Bonus for successful trades in low volatility
        if vol_regime == -1 and trade_outcome.get('is_profitable', False):
            return 0.2
        
        return 0
    
    def _update_performance_tracking(self, trade_outcome: Dict):
        """Update performance tracking metrics"""
        if trade_outcome.get('is_profitable', False):
            self.returns_history.append(trade_outcome.get('rr_achieved', 1.0))
        else:
            self.returns_history.append(-trade_outcome.get('loss_ratio', 1.0))
        
        self.drawdown_history.append(trade_outcome.get('current_drawdown', 0))
        
        # Update Sharpe ratio history
        if len(self.returns_history) >= 20:
            recent_returns = list(self.returns_history)[-20:]
            mean_return = np.mean(recent_returns)
            std_return = np.std(recent_returns)
            if std_return > 0:
                sharpe = mean_return / std_return
                self.sharpe_history.append(sharpe)

class PPOAgent:
    """Proximal Policy Optimization agent for trading"""
    
    def __init__(self, state_dim: int, config, model_path: str = "ppo_trading_model.pkl"):
        self.config = config
        self.trading_config = config.get_trading_config()
        self.model_path = model_path
        
        # Networks
        self.policy_net = PolicyNetwork(state_dim)
        self.value_net = ValueNetwork(state_dim)
        
        # Optimizers
        self.policy_optimizer = optim.Adam(self.policy_net.parameters(), lr=self.trading_config.learning_rate)
        self.value_optimizer = optim.Adam(self.value_net.parameters(), lr=self.trading_config.learning_rate)
        
        # Memory and training
        self.memory = PPOMemory(capacity=self.trading_config.memory_size)
        self.reward_function = AdvancedRewardFunction(config)
        
        # Training parameters
        self.gamma = 0.99
        self.lam = 0.95
        self.clip_ratio = 0.2
        self.value_loss_coef = 0.5
        self.entropy_coef = 0.01
        self.max_grad_norm = 0.5
        
        # Performance tracking
        self.episode_rewards = deque(maxlen=100)
        self.episode_lengths = deque(maxlen=100)
        self.training_step = 0
        
        # Load existing model if available
        self.load_model()
    
    def get_action(self, state: np.ndarray, deterministic: bool = False) -> Tuple[float, float, float]:
        """Get action from current state"""
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            
            if deterministic:
                action = self.policy_net(state_tensor).item()
                value = self.value_net(state_tensor).item()
                log_prob = 0.0  # Not needed for deterministic
            else:
                # Add exploration noise
                action_mean = self.policy_net(state_tensor).item()
                action_std = 0.1  # Fixed std for exploration
                
                # Sample action
                action_dist = Normal(action_mean, action_std)
                action = action_dist.sample().item()
                log_prob = action_dist.log_prob(torch.tensor(action)).item()
                
                # Get value
                value = self.value_net(state_tensor).item()
        
        return action, log_prob, value
    
    def store_experience(self, state: np.ndarray, action: float, reward: float, 
                        next_state: np.ndarray, done: bool, info: Dict):
        """Store experience in memory"""
        experience = Experience(state, action, reward, next_state, done, info)
        _, log_prob, value = self.get_action(state)
        
        self.memory.push(experience, log_prob, value)
    
    def update(self) -> Dict[str, float]:
        """Update the agent using PPO"""
        if len(self.memory.states) < self.trading_config.batch_size:
            return {}
        
        # Compute advantages and returns
        self.memory.compute_advantages_and_returns(self.gamma, self.lam)
        
        # Get training batch
        batch = self.memory.get_batch(self.trading_config.batch_size)
        
        # Normalize advantages
        advantages = batch['advantages']
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        
        # PPO update
        policy_loss, value_loss, entropy_loss = self._ppo_update(batch, advantages)
        
        # Clear memory
        self.memory.clear()
        
        # Update training step
        self.training_step += 1
        
        return {
            'policy_loss': policy_loss,
            'value_loss': value_loss,
            'entropy_loss': entropy_loss,
            'training_step': self.training_step
        }
    
    def _ppo_update(self, batch: Dict, advantages: torch.Tensor) -> Tuple[float, float, float]:
        """Perform PPO update"""
        states = batch['states']
        actions = batch['actions']
        old_log_probs = batch['log_probs']
        returns = batch['returns']
        
        # Forward pass
        action_means = self.policy_net(states).squeeze()
        values = self.value_net(states).squeeze()
        
        # Calculate new log probabilities
        action_stds = torch.full_like(action_means, 0.1)
        action_dists = Normal(action_means, action_stds)
        new_log_probs = action_dists.log_prob(actions)
        
        # Calculate ratios
        ratios = torch.exp(new_log_probs - old_log_probs)
        
        # Calculate policy loss
        surr1 = ratios * advantages
        surr2 = torch.clamp(ratios, 1 - self.clip_ratio, 1 + self.clip_ratio) * advantages
        policy_loss = -torch.min(surr1, surr2).mean()
        
        # Calculate value loss
        value_loss = F.mse_loss(values, returns)
        
        # Calculate entropy loss
        entropy_loss = -action_dists.entropy().mean()
        
        # Total loss
        total_loss = policy_loss + self.value_loss_coef * value_loss + self.entropy_coef * entropy_loss
        
        # Update policy network
        self.policy_optimizer.zero_grad()
        policy_loss.backward(retain_graph=True)
        torch.nn.utils.clip_grad_norm_(self.policy_net.parameters(), self.max_grad_norm)
        self.policy_optimizer.step()
        
        # Update value network
        self.value_optimizer.zero_grad()
        value_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.value_net.parameters(), self.max_grad_norm)
        self.value_optimizer.step()
        
        return policy_loss.item(), value_loss.item(), entropy_loss.item()
    
    def calculate_reward(self, trade_outcome: Dict, confidence: float, 
                        market_features: Dict) -> float:
        """Calculate reward using advanced reward function"""
        return self.reward_function.calculate_reward(trade_outcome, confidence, market_features)
    
    def save_model(self):
        """Save the trained model"""
        try:
            model_data = {
                'policy_net_state_dict': self.policy_net.state_dict(),
                'value_net_state_dict': self.value_net.state_dict(),
                'policy_optimizer_state_dict': self.policy_optimizer.state_dict(),
                'value_optimizer_state_dict': self.value_optimizer.state_dict(),
                'training_step': self.training_step,
                'episode_rewards': list(self.episode_rewards),
                'episode_lengths': list(self.episode_lengths)
            }
            
            torch.save(model_data, self.model_path)
            logger.info(f"PPO model saved to {self.model_path}")
            
        except Exception as e:
            logger.error(f"Error saving PPO model: {e}")
    
    def load_model(self):
        """Load the trained model"""
        try:
            if os.path.exists(self.model_path):
                model_data = torch.load(self.model_path, map_location='cpu')
                
                # Try to load with strict=False to allow dimension mismatches
                try:
                    self.policy_net.load_state_dict(model_data['policy_net_state_dict'], strict=False)
                    self.value_net.load_state_dict(model_data['value_net_state_dict'], strict=False)
                    logger.warning("Loaded PPO model with dimension mismatches - some layers reset to random")
                except Exception as load_err:
                    logger.warning(f"Could not load model weights (dimension mismatch): {load_err}")
                    logger.info("Starting with fresh randomly initialized model")
                    return False
                
                try:
                    self.policy_optimizer.load_state_dict(model_data['policy_optimizer_state_dict'])
                    self.value_optimizer.load_state_dict(model_data['value_optimizer_state_dict'])
                except Exception:
                    logger.warning("Could not load optimizer states - reinitializing")
                
                self.training_step = model_data.get('training_step', 0)
                self.episode_rewards = deque(model_data.get('episode_rewards', []), maxlen=100)
                self.episode_lengths = deque(model_data.get('episode_lengths', []), maxlen=100)
                
                logger.info(f"PPO model loaded from {self.model_path}")
                return True
                
        except Exception as e:
            logger.error(f"Error loading PPO model: {e}")
        
        return False
    
    def get_performance_metrics(self) -> Dict[str, float]:
        """Get current performance metrics"""
        if not self.episode_rewards:
            return {}
        
        recent_rewards = list(self.episode_rewards)[-20:]
        
        return {
            'avg_reward': float(np.mean(recent_rewards)),
            'std_reward': float(np.std(recent_rewards)),
            'max_reward': float(np.max(recent_rewards)),
            'min_reward': float(np.min(recent_rewards)),
            'training_step': self.training_step,
            'episodes_completed': len(self.episode_rewards)
        }

class RLSystem:
    """Main RL system wrapper"""
    
    def __init__(self, config, state_dim: int):
        self.config = config
        self.trading_config = config.get_trading_config()
        self.state_dim = state_dim
        
        # Initialize PPO agent
        self.agent = PPOAgent(state_dim, config)
        
        # State management
        self.current_state = None
        self.previous_state = None
        self.state_history = deque(maxlen=1000)
        
        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_reward = 0.0
        
        # Feature normalization
        self.feature_mean = None
        self.feature_std = None
        self.normalization_samples = deque(maxlen=1000)
    
    def predict(self, state_vector: np.ndarray) -> float:
        """Predict confidence from state vector (alias for get_action)"""
        try:
            # Ensure state vector has correct dimensions
            if len(state_vector) < self.state_dim:
                # Pad with zeros
                padded = np.zeros(self.state_dim, dtype=np.float32)
                padded[:len(state_vector)] = state_vector
                state_vector = padded
            elif len(state_vector) > self.state_dim:
                state_vector = state_vector[:self.state_dim]
            
            # Normalize state
            state_vector = self._normalize_state(state_vector)
            
            # Get action (confidence) from agent
            confidence, _, _ = self.agent.get_action(state_vector, deterministic=True)
            
            # Store state for learning
            self.previous_state = self.current_state
            self.current_state = state_vector
            
            return np.clip(confidence, 0.1, 0.95)
            
        except Exception as e:
            logger.error(f"RL predict error: {e}")
            return 0.75  # Default confidence
    
    def predict_confidence(self, market_features: Dict, signal_data: Dict) -> float:
        """Predict confidence using RL agent"""
        try:
            # Convert features to state vector
            state = self._features_to_state(market_features, signal_data)

            # Pad/truncate state to match expected state_dim (fix dimension mismatch)
            if len(state) < self.state_dim:
                padded = np.zeros(self.state_dim, dtype=np.float32)
                padded[:len(state)] = state
                state = padded
            elif len(state) > self.state_dim:
                state = state[:self.state_dim]
            
            # Get action from agent
            confidence, _, _ = self.agent.get_action(state, deterministic=False)
            
            # Store state for learning
            self.current_state = state
            
            return np.clip(confidence, 0.1, 0.95)
            
        except Exception as e:
            logger.error(f"RL prediction error: {e}")
            return 0.75  # Default confidence
    
    def learn_from_outcome(self, trade_outcome: Dict, market_features: Dict):
        """Learn from trade outcome"""
        try:
            if self.current_state is None or self.previous_state is None:
                return
            
            # Calculate reward
            confidence = trade_outcome.get('confidence', 0.75)
            reward = self.agent.calculate_reward(trade_outcome, confidence, market_features)
            
            # Store experience
            done = trade_outcome.get('is_profitable', False)  # Episode ends on profitable trade
            info = {
                'trade_outcome': trade_outcome,
                'market_features': market_features
            }
            
            self.agent.store_experience(
                self.previous_state, confidence, reward, 
                self.current_state, done, info
            )
            
            # Update performance tracking
            self.total_trades += 1
            if trade_outcome.get('is_profitable', False):
                self.winning_trades += 1
            
            self.total_reward += reward
            
            # Update agent if enough experiences
            if len(self.agent.memory.states) >= self.trading_config.batch_size:
                update_info = self.agent.update()
                if update_info:
                    logger.info(f"RL Update: {update_info}")
            
            # Update state history
            self.previous_state = self.current_state
            
        except Exception as e:
            logger.error(f"RL learning error: {e}")
    
    def _features_to_state(self, market_features: Dict, signal_data: Dict) -> np.ndarray:
        """Convert features to state vector"""
        # Combine all features
        all_features = {**market_features, **signal_data}
        
        # Convert to numpy array
        feature_values = []
        feature_names = sorted(all_features.keys())
        
        for name in feature_names:
            value = all_features.get(name, 0)
            if isinstance(value, (int, float)) and not np.isnan(value):
                feature_values.append(value)
            else:
                feature_values.append(0)
        
        state = np.array(feature_values, dtype=np.float32)
        
        # Normalize state
        state = self._normalize_state(state)
        
        return state
    
    def _normalize_state(self, state: np.ndarray) -> np.ndarray:
        """Normalize state using running statistics"""
        # Add to normalization samples
        self.normalization_samples.append(state)
        
        # Update normalization statistics
        if len(self.normalization_samples) >= 100:
            samples_array = np.array(list(self.normalization_samples))
            self.feature_mean = np.mean(samples_array, axis=0)
            self.feature_std = np.std(samples_array, axis=0) + 1e-8
        
        # Apply normalization
        if self.feature_mean is not None and self.feature_std is not None:
            state = (state - self.feature_mean) / self.feature_std
        
        return state
    
    def save_model(self):
        """Save the RL model"""
        self.agent.save_model()
    
    def load_model(self):
        """Load the RL model"""
        return self.agent.load_model()
    
    def get_performance_metrics(self) -> Dict[str, float]:
        """Get performance metrics"""
        metrics = self.agent.get_performance_metrics()
        
        if self.total_trades > 0:
            metrics['win_rate'] = self.winning_trades / self.total_trades
            metrics['total_trades'] = self.total_trades
            metrics['total_reward'] = self.total_reward
        
        return metrics
