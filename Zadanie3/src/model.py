import numpy as np

import torch as T
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.distributions import Beta
from torch.utils.data.sampler import BatchSampler, SubsetRandomSampler

from src.Net import Net

from src.Net import Actor, Critic
from gym import spaces


class Agent:
    max_grad_norm = 0.5
    clip_param = 0.1
    ppo_epoch = 10
    buffer_capacity, batch_size = 2000, 128

    def __init__(self, alpha, gamma, env):
        self.alpha = alpha
        self.gamma = gamma
        self.action_space = env.action_space
        self.observation_space = env.observation_space

        self.training_step = 0
        self.device = T.device("cuda" if T.cuda.is_available() else "cpu")

        self.actor = Actor(
            alpha=self.alpha,
            obs_space=self.observation_space.shape[0],
            action_space=self.action_space.n if hasattr(self.action_space, "n") else self.action_space.shape[0]
        ).double().to(self.device)

        self.critic = Critic(
            alpha=self.alpha,
            obs_space=self.observation_space.shape[0],
            action_space=self.action_space.n if hasattr(self.action_space, "n") else self.action_space.shape[0]
        ).double().to(self.device)

        self.transition = np.dtype(
            [('s', np.float64, self.observation_space.shape), ('a', np.float64, self.action_space.shape),
             ('a_logp', np.float64),
             ('r', np.float64), ('s_n', np.float64, self.observation_space.shape)])

        self.buffer = np.empty(self.buffer_capacity, dtype=self.transition)
        self.counter = 0

    def select_action(self, state):
        state_x = T.from_numpy(state).float().to(self.device)
        action = self.actor.forward(state_x).detach().numpy()

        if type(self.action_space) == spaces.Box:
            action = action  # TODO Implement action handling if continuous
        elif type(self.action_space) == spaces.Discrete:
            action = action  # TODO Implement action handling if discrete
        else:
            raise Exception("Invalid action space type.")
        return action
        # return action.clip(min=self.action_space.low, max=self.action_space.high)  # TODO: clip action?

    def store(self, transition):
        self.buffer[self.counter] = transition
        self.counter += 1
        if self.counter == self.buffer_capacity:
            self.counter = 0
            return True
        else:
            return False

    def update(self):  # TODO Implement update
        pass


class Agent_old:
    max_grad_norm = 0.5
    clip_param = 0.1
    ppo_epoch = 10
    buffer_capacity, batch_size = 2000, 128

    def __init__(self, alpha, gamma):
        self.alpha = alpha
        self.gamma = gamma

        self.transition = np.dtype(
            [('s', np.float64, (self.img_stack, 96, 96)), ('a', np.float64, (3,)), ('a_logp', np.float64),
             ('r', np.float64), ('s_n', np.float64, (self.img_stack, 96, 96))])
        self.training_step = 0
        self.device = T.device("cuda" if T.cuda.is_available() else "cpu")

        self.net = Net(alpha=self.alpha, gamma=self.gamma,
                       img_stack=self.img_stack).double().to(self.device)

        self.buffer = np.empty(self.buffer_capacity, dtype=self.transition)
        self.counter = 0

    def select_action(self, state):
        state = T.from_numpy(state).double().to(self.device).unsqueeze(0)
        with T.no_grad():
            alpha, beta = self.net(state)[0]
        dist = Beta(alpha, beta)
        action = dist.sample()
        a_logp = dist.log_prob(action).sum(dim=1)
        action = action.squeeze().cpu().numpy()
        a_logp = a_logp.item()

        return action, a_logp

    def save_param(self, name):
        T.save(self.net.state_dict(), 'data/model/' + name + '.pkl')

    def store(self, transition):
        self.buffer[self.counter] = transition
        self.counter += 1
        if self.counter == self.buffer_capacity:
            self.counter = 0
            return True
        else:
            return False

    def load_param(self, name):
        self.net.load_state_dict(T.load('data/model/' + name + '.pkl'))

    def update(self):
        self.training_step += 1

        s = T.tensor(self.buffer['s'], dtype=T.double).to(self.device)
        a = T.tensor(self.buffer['a'], dtype=T.double).to(self.device)
        r = T.tensor(self.buffer['r'], dtype=T.double).to(
            self.device).view(-1, 1)
        s_n = T.tensor(self.buffer['s_n'], dtype=T.double).to(self.device)

        old_a_logp = T.tensor(self.buffer['a_logp'], dtype=T.double).to(
            self.device).view(-1, 1)

        with T.no_grad():
            target_v = r + self.gamma * self.net(s_n)[1]
            adv = target_v - self.net(s)[1]

        for _ in range(self.ppo_epoch):
            for index in BatchSampler(SubsetRandomSampler(range(self.buffer_capacity)), self.batch_size, False):
                alpha, beta = self.net(s[index])[0]
                dist = Beta(alpha, beta)
                a_logp = dist.log_prob(a[index]).sum(dim=1, keepdim=True)
                ratio = T.exp(a_logp - old_a_logp[index])

                surr1 = ratio * adv[index]
                surr2 = T.clamp(ratio, 1.0 - self.clip_param,
                                1.0 + self.clip_param) * adv[index]
                action_loss = -T.min(surr1, surr2).mean()
                value_loss = F.smooth_l1_loss(
                    self.net(s[index])[1], target_v[index])
                loss = action_loss + 2. * value_loss

                self.net.optimizer.zero_grad()
                loss.backward()
                # nn.utils.clip_grad_norm_(self.net.parameters(), self.max_grad_norm)
                self.net.optimizer.step()
