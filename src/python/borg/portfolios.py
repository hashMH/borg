"""@author: Bryan Silverthorn <bcs@cargo-cult.org>"""

import itertools
import numpy
import borg

logger = borg.get_logger(__name__, default_level = "INFO")

class RandomPortfolio(object):
    """Random portfolio."""

    def __call__(self, task, suite, budget):
        """Run the portfolio."""

        solvers = suite.solvers.values()
        selected = numpy.random.randint(len(solvers))

        return solvers[selected].start(task).run_then_stop(budget.cpu_seconds)

class UniformPortfolio(object):
    """Portfolio that runs every solver once."""

    def __call__(self, task, suite, budget):
        """Run the portfolio."""

        budget_each = budget.cpu_seconds / (len(suite.solvers) * 100)
        processes = [s.start(task) for s in suite.solvers.values()]
        next_process = itertools.cycle(processes)

        def finished():
            return \
                budget.cpu_seconds - sum(p.elapsed for p in processes) < budget_each \
                or all(p.terminated for p in processes)

        while not finished():
            process = next_process.next()

            if not process.terminated:
                answer = process.run_then_pause(budget_each)

                if suite.domain.is_final(task, answer):
                    return answer

        return None

class BaselinePortfolio(object):
    """Portfolio that runs the best train-set solver."""

    def __init__(self, suite, training):
        """Initialize."""

        solver_names = list(suite.solvers)
        outcome_counts = training.to_bins_array(solver_names, 1).astype(numpy.double)
        success_rates = outcome_counts[..., 0] / numpy.sum(outcome_counts, axis = -1)
        mean_rates = numpy.mean(success_rates, axis = 0)

        self._solver_name = solver_names[numpy.argmax(mean_rates)]

    def __call__(self, task, suite, budget):
        """Run the portfolio."""

        process = suite.solvers[self._solver_name].start(task)
        
        return process.run_then_stop(budget.cpu_seconds)

class OraclePortfolio(object):
    """Optimal prescient discrete-budget portfolio."""

    def __init__(self, subsample = None):
        self._subsample = subsample

    def __call__(self, task, suite, budget):
        """Run the portfolio."""

        # XXX fix the solver_names situation

        # grab known run data
        budget_count = 100
        solver_names = sorted(suite.solvers)
        data = suite.run_data.filter(task)

        if self._subsample is not None:
            data = data.collect_systematic([self._subsample])

        bins = data.to_bins_array(solver_names, budget_count)[0].astype(numpy.double) + 1e-16
        bins[:, -2] += 1e-2 # if all else fails...
        rates = bins / numpy.sum(bins, axis = -1)[..., None]
        log_survival = numpy.log(1.0 - numpy.cumsum(rates[:, :-1], axis = -1))

        # make a plan
        interval = data.get_common_budget() / budget_count
        planner = borg.planners.KnapsackPlanner()
        plan = planner.plan(log_survival[None, ...])

        # and follow through
        remaining = budget.cpu_seconds

        for (s, b) in plan:
            this_budget = (b + 1) * interval

            assert remaining - this_budget > -1e-1

            process = suite.solvers[solver_names[s]].start(task)
            answer = process.run_then_stop(this_budget)
            remaining -= this_budget

            if suite.domain.is_final(task, answer):
                return answer

        return None

class PreplanningPortfolio(object):
    """Preplanning discrete-budget portfolio."""

    def __init__(self, suite, model, planner = None):
        """Initialize."""

        if planner is None:
            planner = borg.planners.KnapsackPlanner()
            #planner = borg.planners.ReorderingPlanner(borg.planners.MaxLengthKnapsackPlanner(12))

        self._solver_names = sorted(suite.solvers)
        self._model = model
        self._plan = planner.plan(self._model.log_survival[..., :-1])

        logger.info("preplanned plan: %s", self._plan)

    def __call__(self, task, suite, budget):
        """Run the portfolio."""

        remaining = budget.cpu_seconds

        for (s, b) in self._plan:
            this_budget = (b + 1) * self._model.interval

            assert remaining - this_budget > -1e-1

            process = suite.solvers[self._solver_names[s]].start(task)
            answer = process.run_then_stop(this_budget)
            remaining -= this_budget

            if suite.domain.is_final(task, answer):
                return answer

        return None

class PureModelPortfolio(object):
    """Hybrid mixture-model portfolio."""

    def __init__(self, suite, model, regress = None, planner = borg.planners.default):
        """Initialize."""

        self._model = model
        self._regress = regress
        self._planner = planner
        self._solver_names = sorted(suite.solvers)
        self._runs_limit = 256

    def __call__(self, task, suite, budget):
        """Run the portfolio."""

        with borg.accounting() as accountant:
            # predict RTD weights
            if self._regress is None:
                initial_model = self._model
            else:
                (feature_names, feature_values) = suite.domain.compute_features(task)
                feature_dict = dict(zip(feature_names, feature_values))
                feature_values_sorted = [feature_dict[f] for f in sorted(feature_names)]
                #(predicted_weights,) = numpy.log(self._regress.predict([feature_values_sorted]))
                (predicted_weights,) = numpy.log(self._regress.predict([task], [feature_values_sorted]))
                initial_model = self._model.with_weights(predicted_weights)

            # compute and execute a solver schedule
            plan = []
            failures = []

            for i in xrange(self._runs_limit):
                elapsed = accountant.total.cpu_seconds

                if budget.cpu_seconds <= elapsed:
                    break

                if len(plan) == 0:
                    model = initial_model.condition(failures)
                    remaining = budget.cpu_seconds - elapsed
                    remaining_b = int(numpy.ceil(remaining / model.interval))
                    plan = \
                        self._planner.plan(
                            model.log_survival[..., :remaining_b],
                            model.log_weights,
                            )

                (s, b) = plan.pop(0)
                remaining = budget.cpu_seconds - accountant.total.cpu_seconds
                duration = min(remaining, (b + 1) * model.interval)
                process = suite.solvers[self._solver_names[s]].start(task)
                answer = process.run_then_stop(duration)

                if suite.domain.is_final(task, answer):
                    return answer
                else:
                    failures.append((s, b))

            return None

