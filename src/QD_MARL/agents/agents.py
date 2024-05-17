import os
import sys
from utils.print_outputs import *

sys.path.append(".")
import random
import time
from copy import deepcopy
from math import sqrt
import pettingzoo

from inspyred import ec
import numpy as np


class Agent:
    def __init__(self, name, squad, set_, tree, manual_policy, to_optimize):
        self._name = name
        self._squad = squad
        self._set = set_
        self._tree = tree.deep_copy() if tree is not None else None
        self._manual_policy = manual_policy
        self._to_optimize = to_optimize
        self._score = []

    def get_name(self):
        return self._name

    def get_squad(self):
        return self._squad

    def get_set(self):
        return self._set

    def to_optimize(self):
        return self._to_optimize

    def get_tree(self):
        return self._tree.deep_copy()

    def get_output(self, observation):
        if self._to_optimize:
            return self._tree.get_output(observation)
        else:
            return self._manual_policy.get_output(observation)

    def set_reward(self, reward):
        self._tree.set_reward(reward)
        self._score[-1] += reward

    def get_score_statistics(self, params):
        return getattr(np, f"{params['type']}")(a=self._score, **params["params"])

    def new_episode(self):
        self._score.append(0)

    def has_policy(self):
        return not self._manual_policy is None

    def __str__(self):
        return f"Name: {self._name}; Squad: {self._squad}; Set: {self._set}; Optimize: {str(self._to_optimize)}"

class CoachAgent:

    # Coach agent which select the team of agent from the pool produced by the initial population
    # of map elite, it is based on hte Genetic Algorithm from inspyred library
    # https://pythonhosted.org/inspyred/reference.html#module-inspyred.ec

    # Class arguments:
    # team_fitnesses: list of fitnesses of the agents in the pool
    # initial_pop: initial population of the map elite
    # config: configuration of the algorithm

    # Class methods:
    # init_algorithm: initialize the algorithm parameters
    # set_generator: set the generator of the algorithm, generates candidates for the function to optimize
    # set_evaluator: set the evaluator of the algorithm, evaluates the candidates
    # get_final_pop: get the final population of the algorithm

    def __init__(self, config, me = None, n_teams = 1):
        self._config = config
        self._me = me
        self.random = random.Random()
        self.random.seed(self._config["seed"])
        self._pop_size = self._config["pop_size"]
        self._batch_size = self._config["batch_size"]
        self._algorithm = self.set_algorithm()
        self._pop_descs = []
        self._pop_fitnesses = []
        self._n_teams = n_teams
        
    def get_n_teams(self):
        return self._n_teams
    
    def set_n_teams(self, n_teams):
        self._n_teams = n_teams
        
    def set_algorithm(self):
        # Type of avilable algorithms:
        # ec.GA, ec.EvolutionaryComputation
        name = self._config["algorithm"]

        return getattr(ec, name)(self.random)

    def init_algogrithm(self):
        self._algorithm.terminator = ec.terminators.evaluation_termination
        self._algorithm.replacer = ec.replacers.generational_replacement
        self._algorithm.variator = [
            ec.variators.uniform_crossover,
            ec.variators.gaussian_mutation,
        ]
        self._algorithm.selector = ec.selectors.tournament_selection

    def set_generator(self, random, args):
        # generate candidates
        # return list of lists of indices in population
        return [random.randint(0, len(self._pop_descs)-1) for _ in range(self._batch_size)]

    def set_evaluator(self, candidates, args):
        # evaluate the candidates
        # return list of tuples (index in population, fitness)
        res = []
        for cs in candidates:
            team = []
            index = []
            for c in cs:
                team.append(self._pop_fitnesses[c])
            res.append(getattr(np, self._config["statistics"]["team"]["type"])(a=team, **self._config["statistics"]["team"]["params"]))
        return res
    
    def get_descriptors(self, index):
        descriptors = []
        for i in index:
            descriptors.append(self._pop_descs[i])
        return descriptors

    def ask(self):
        teams = []
        me_data = self._me._archive.data()
        self._pop_descs = me_data["solution"]
        self._pop_fitnesses = me_data["objective"]

        final_pop = self._algorithm.evolve(
            generator=self.set_generator,
            evaluator=self.set_evaluator,
            maximaze=True,
            initial_pop_storage=self._pop_fitnesses,
        )
        final_pop_fitnesses = np.asarray([ind.fitness for ind in final_pop])
        final_pop_candidates = np.asarray([ind.candidate for ind in final_pop])
        
        sort_indexes = sorted(range(len(final_pop_fitnesses)), key=final_pop_fitnesses.__getitem__, reverse=True)
        final_pop_fitnesses = final_pop_fitnesses[sort_indexes]
        final_pop_candidates = final_pop_candidates[sort_indexes]
        solution_fitness = final_pop_fitnesses[:self._n_teams]
        solution_pop = final_pop_candidates[:self._n_teams]
        for j in range(self._n_teams):
            solution = []
            for i in range(self._batch_size):
                solution.append(self._pop_descs[solution_pop[j][i]])
            me_pop = self._me.ask(solution)
            teams.append(me_pop)
        return teams
    
    def tell(self, fitnesses, trees):
        self._pop_trees = trees
        self._pop_fitnesses = fitnesses
        self.set_best_team(trees, fitnesses)

    def set_best_team(self, teams, teams_fitnesses):
        # Set the best squad to the coach agent
        # squad: list of squads, each squad is a list of agents
        
        for index, team in enumerate(teams):
            team_fitness = np.mean(teams_fitnesses[index])
            if team_fitness > self._best_fitness:
                self._best_team = team
                self._best_fitness = team_fitness
                print_info(f"New best team with fitness: {team_fitness}")

    def get_best_squad(self):
        # Get the best squad
        return self._best_team

    def __str__(self):
        return f"Coach config: {self._config}"
