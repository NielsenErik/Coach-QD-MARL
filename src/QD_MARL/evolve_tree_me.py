#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    experiment_launchers.history_reuse_gym
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    This module allows to evolve diverse trees for a domain
    by using Novelty search.

    :copyright: (c) 2021 by Leonardo Lucio Custode.
    :license: MIT, see LICENSE for more details.
"""
import os
import sys
sys.path.append("../..")
import gym
from time import time, sleep
import utils
import random
import numpy as np
from tqdm import tqdm
from copy import deepcopy
from algorithms import grammatical_evolution, map_elites
from decisiontrees import QLearningLeafFactory, ConditionFactory, \
        RLDecisionTree
from joblib import Parallel, delayed

def pretrain_tree(t, rb):
    """
    Pretrains a tree

    :t: A tree
    :rb: The replay buffer
    :returns: The pretrained tree
    """
    if t is None:
        return None
    for e in rb:
        t.empty_buffers()
        if len(e) > 0:
            for s, a, r, sp in e:
                t.force_action(s, a)
                t.set_reward(r)
            t.set_reward_end_of_episode()
    return t


def evaluate_tree(tree, config):
    """
    Evaluates the tree

    :tree: The tree to evaluate
    :config: The config
    :returns: A tuple (episodes, fitness)
    """
    # Check if the tree is valid
    if tree is None:
        return ([], -10**5, None)

    env = gym.make(config["env"]["env_name"])
    episodes = []
    cum_rews = []

    # Iterate over the episodes
    for i in range(config["training"]["episodes"]):
        tree.empty_buffers()
        episodes.append([])
        env.seed(i)
        obs = env.reset()
        done = False
        cum_rews.append(0)
        step = 0
        while not done:
            action = tree.get_output(obs)
            obs, rew, done, _ = env.step(action)
            tree.set_reward(rew)
            cum_rews[-1] += rew
            # episodes[-1].append([list(obs), action, rew])
            if step != 0:
                episodes[-1][-1][-1] = obs
            step += 1
            episodes[-1].append([obs, action, rew, None])
        tree.set_reward_end_of_episode()

    return episodes, np.mean(cum_rews), tree


def evaluate(trees, config, replay_buffer, map_):
    """
    Evaluates the fitness of the population of trees

    :trees: A list of trees
    :config: A dictionary with all the settings
    :replay_buffer: a list of episodes (lists of (state, action, rew))
    :map_: a mapping function
    :returns: A list of (float, tree)
    """
    ti = time()
    if len(replay_buffer) > 0:
        trees = map_(pretrain_tree, trees, replay_buffer)

    print("Pretraining took", time() - ti, "\bs")


    ti = time()
    ti = time()
    outputs = map_(evaluate_tree, [trees[i] for i in range(len(trees))], config)
    print("Training took", time() - ti, "\bs")

    best_fitness = -float("inf")
    best_episodes = None
    ret_values = [None for _ in range(len(trees))]
    for index, (episodes, fitness, tree) in zip(list(range(len(trees))), outputs):
        trees[index] = tree
        ret_values[index] = (fitness, trees[index])
        """
        replay_buffer.extend(episodes)
        while len(replay_buffer) > config["training"]["max_buffer_size"]:
            del replay_buffer[0]
        """
        if fitness > best_fitness:
            best_episodes = episodes
        trees.append(tree)

    return ret_values


def produce_tree(config, log_path, debug=False):
    """
    Produces a tree for the selected problem by using the Grammatical Evolution

    :config: a dictionary containing all the parameters
    :log_path: a path to the log directory
    """
    # Setup GE
    me_config = config["me"]

    # Build classes of the operators from the config file
    me_config["c_factory"] = ConditionFactory()
    me_config["l_factory"] = QLearningLeafFactory(
        config["leaves"]["params"],
        config["leaves"]["decorators"]
    )
    me = map_elites.MapElites(**me_config)

    # Init replay buffer
    replay_buffer = []

    # Retrieve the map function from utils
    map_ = utils.get_map(config["training"]["jobs"], debug)
    # Initialize best individual
    best, best_fit, new_best = None, -float("inf"), False

    with open(os.path.join(log_path, "log.txt"), "a") as f:
        f.write(f"Generation Min Mean Max Std\n")
    print(f"{'Generation' : <10} {'Min': <10} {'Mean': <10} \
      {'Max': <10} {'Std': <10} {'Invalid': <10} {'Best': <10}")

    trees = me.init_pop()
    print(trees)
    trees = [RLDecisionTree(t, config["training"]["gamma"]) for t in trees]
    # Compute the fitnesses
    # We need to return the trees in order to retrieve the
    #   correct values for the leaves when using the
    #   parallelization
    return_values = evaluate(trees, config, replay_buffer, map_)
    fitnesses = [r[0] for r in return_values]
    trees = [r[1] for r in return_values]

    # Check whether the best has to be updated
    print(fitnesses)
    amax = np.argmax(fitnesses)
    max_ = fitnesses[amax]
    me.init_tell(fitnesses, trees)
    # Iterate over the generations
    for i in range(config["training"]["generations"]):
        # Retrieve the current population
        trees = me.ask()
        print(trees)
        trees = [RLDecisionTree(t, config["training"]["gamma"]) for t in trees]
        # Compute the fitnesses
        # We need to return the trees in order to retrieve the
        #   correct values for the leaves when using the
        #   parallelization
        return_values = evaluate(trees, config, replay_buffer, map_)
        fitnesses = [r[0] for r in return_values]
        trees = [r[1] for r in return_values]

        # Check whether the best has to be updated
        amax = np.argmax(fitnesses)
        max_ = fitnesses[amax]

        if max_ > best_fit:
            best_fit = max_
            best = trees[amax]
            new_best = True

        # Tell the fitnesses to the GE
        me.tell(fitnesses)

        # Compute stats
        fitnesses = np.array(fitnesses)
        valid = fitnesses != -100000
        min_ = np.min(fitnesses[valid])
        mean = np.mean(fitnesses[valid])
        max_ = np.max(fitnesses[valid])
        std = np.std(fitnesses[valid])
        invalid = np.sum(fitnesses == -100000)

        print(f"{i: <10} {min_: <10.2f} {mean: <10.2f} \
          {max_: <10.2f} {std: <10.2f} {invalid: <10} {best_fit: <10.2f}")

        # Update the log file
        with open(os.path.join(log_path, "log.txt"), "a") as f:
            f.write(f"{i} {min_} {mean} {max_} {std} {invalid}\n")
            if new_best:
                f.write(f"New best: {best}; Fitness: {best_fit}\n")
                with open(join("best_tree.mermaid"), "w") as f:
                    f.write(str(best))
        new_best = False
    return best


if __name__ == "__main__":
    import json
    import utils
    import shutil
    import argparse
    from joblib import parallel_backend

    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="Path of the config file to use")
    parser.add_argument("--debug", action="store_true", help="Debug flag")
    parser.add_argument("seed", type=int, help="Random seed to use")
    args = parser.parse_args()

    # Load the config file
    config = json.load(open(args.config))

    # Set the random seed
    random.seed(args.seed)
    np.random.seed(args.seed)

    # Setup logging
    logdir_name = utils.get_logdir_name()
    log_path = f"logs/me/gym/{logdir_name}"
    join = lambda x: os.path.join(log_path, x)
    #exp = Experiment(args.seed, log_path, **args.config)
    os.makedirs(log_path, exist_ok=False)
    shutil.copy(args.config, join("config.json"))
    with open(join("seed.log"), "w") as f:
        f.write(str(args.seed))

    best = produce_tree(config, log_path, args.debug)
