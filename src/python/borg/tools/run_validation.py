"""
@author: Bryan Silverthorn <bcs@cargo-cult.org>
"""

import plac

if __name__ == "__main__":
    from borg.tools.run_validation import main

    plac.call(main)

import os.path
import csv
import uuid
import itertools
import numpy
import cargo

logger = cargo.get_logger(__name__, default_level = "INFO")

def solve_fake(solver_name, cnf_path, budget):
    """Recycle a previous solver run."""

    csv_path = cnf_path + ".rtd.csv"
    answer_map = {"": None, "True": True, "False": False}
    runs = []

    if os.path.exists(csv_path):
        with open(csv_path) as csv_file:
            reader = csv.reader(csv_file)

            for (name, seed, run_budget, cost, answer) in reader:
                if name == solver_name and float(run_budget) >= budget:
                    runs.append((seed, cost, answer))

    if runs:
        (seed, cost, answer) = cargo.grab(runs)
        cost = float(cost)

        if cost > budget:
            cost = budget
            answer = None
        else:
            answer = answer_map[answer]

        return (int(seed), cost, answer)
    else:
        raise RuntimeError("no applicable runs of {0} on {1}".format(solver_name, cnf_path))

core_solvers = {
    "TNM": lambda *args: solve_fake("TNM", *args),
    "march_hi": lambda *args: solve_fake("march_hi", *args),
    "cryptominisat-2.9.0": lambda *args: solve_fake("cryptominisat-2.9.0", *args),
    }

def run_validation(name, train_paths, test_paths, budget, split):
    """Make a validation run."""

    solve = borg.portfolios.trainers[name](core_solvers, train_paths)
    successes = []

    for test_path in test_paths:
        (seed, cost, answer) = solve(test_path, budget)

        if answer is not None:
            successes.append(cost)

    rate = float(len(successes)) / len(test_paths)

    logger.info("method %s had final success rate %.2f", name, rate)

    return \
        zip(
            itertools.repeat(name),
            itertools.repeat(budget),
            sorted(successes),
            numpy.arange(len(successes) + 1.0) / len(test_paths),
            itertools.repeat(split),
            )

@plac.annotations(
    out_path = ("path to results file", "positional", None, os.path.abspath),
    tasks_root = ("path to task files", "positional", None, os.path.abspath),
    workers = ("submit jobs?", "option", "w", int),
    )
def main(out_path, tasks_root, workers = 0):
    """Collect validation results."""

    cargo.enable_default_logging()

    def yield_runs():
        paths = list(cargo.files_under(tasks_root, ["*.cnf"]))
        examples = int(round(min(500, len(paths)) * 0.50))

        for _ in xrange(8):
            shuffled = sorted(paths, key = lambda _ : numpy.random.rand())
            train_paths = shuffled[:examples]
            test_paths = shuffled[examples:]
            split = uuid.uuid4()

            for name in trainers:
                yield (run_validation, [name, train_paths, test_paths, 5000.0, split])

    with open(out_path, "w") as out_file:
        writer = csv.writer(out_file)

        writer.writerow(["name", "budget", "cost", "rate", "split"])

        cargo.distribute_or_labor(yield_runs(), workers, lambda _, r: writer.writerows(r))

