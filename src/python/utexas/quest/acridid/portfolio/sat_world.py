"""
utexas/acridid/portfolio/sat_world.py

The world of SAT.

@author: Bryan Silverthorn <bcs@cargo-cult.org>
"""

import numpy

from itertools import izip
from contextlib import closing
from collections import (
    Sequence,
    defaultdict,
    )
from sqlalchemy import and_
from sqlalchemy.sql.functions import random as sql_random
from cargo.log import get_logger
from cargo.flags import (
    Flag,
    FlagSet,
    IntRanges,
    )
from utexas.quest.acridid.core import (
    SAT_SolverRun,
    AcrididSession,
    )
from utexas.quest.acridid.portfolio.world import (
    Task,
    World,
    Action,
    Outcome,
    )

log = get_logger(__name__)

class SAT_WorldAction(Action):
    """
    An action in the world.
    """

    def __init__(self, n, solver, configuration, cutoff):
        """
        Initialize.
        """

        self.n = n
        self.solver        = solver
        self.configuration = configuration
        self.cutoff        = cutoff

    def __str__(self):
        """
        Return a human-readable description of this action.
        """

        return "%s_%ims" % (self.solver.name, int(self.cutoff.as_s * 1000))

class SAT_WorldTask(Task):
    """
    A task in the world.
    """

    def __init__(self, n, task):
        """
        Initialize.

        @param task: SAT task description.
        """

        self.n = n
        self.task = task

    def __str__(self):
        """
        Return a human-readable description of this task.
        """

        return "%s" % (self.task.path,)

class SAT_Outcome(Outcome):
    """
    An outcome of an action in the world.
    """

    def __init__(self, n, utility):
        """
        Initialize.
        """

        self.n       = n
        self.utility = utility

    def __str__(self):
        """
        Return a human-readable description of this outcome.
        """

        return str(self.utility)

    @staticmethod
    def from_run(run):
        """
        Return an outcome from a solver run.
        """

        return SAT_Outcome.from_bool(run.outcome)

    @staticmethod
    def from_bool(bool):
        """
        Return an outcome from True, False, or None.
        """

        if bool is None:
            return SAT_Outcome.UNKNOWN
        elif bool is True:
            return SAT_Outcome.SAT
        else:
            return SAT_Outcome.UNSAT

# outcome constants
SAT_Outcome.SAT     = SAT_Outcome(0, 1.0)
SAT_Outcome.UNSAT   = SAT_Outcome(0, 1.0)
SAT_Outcome.UNKNOWN = SAT_Outcome(1, 0.0)

class SAT_World(World):
    """
    Components of the SAT world.
    """

    def __init__(self, actions, tasks):
        """
        Initialize.
        """

        self.actions   = actions
        self.tasks     = tasks
        self.outcomes  = (SAT_Outcome.SAT, SAT_Outcome.UNSAT)
        self.utilities = numpy.array([o.utility for o in self.outcomes])

    def act_all(self, tasks, actions, nrestarts = 1, random = numpy.random):
        """
        Return a history of C{nrestarts} outcomes sampled from each of C{tasks}.

        @return: {task: (action, outcome)}
        """

        # build a reverse task map
        world_tasks = dict((t.task.uuid, t) for t in tasks)

        # hit the database
        session = AcrididSession()

        # FIXME broken

        with closing(session):
            events = []

            for action in actions:
                filter  = \
                    and_(
                        SAT_SolverRun.task_uuid.in_([t.task.uuid for t in tasks]),
                        SAT_SolverRun.solver        == action.solver,
                        SAT_SolverRun.configuration == action.configuration,
                        SAT_SolverRun.cutoff        >= action.cutoff,
                        )
                runs    = session.query(SAT_SolverRun).filter(filter).order_by(sql_random())[:nrestarts]

                events.extend((world_tasks[r.task.uuid], action, SAT_Outcome.from_run(r)) for r in runs)

            return events

    def act(self, task, action, random = numpy.random):
        """
        Retrieve a random sample.
        """

        # FIXME should set the postgres random seed using the passed PRNG

        session = AcrididSession()

        with closing(session):
            filter  = \
                and_(
                    SAT_SolverRun.task          == task.task,
                    SAT_SolverRun.solver        == action.solver,
                    SAT_SolverRun.configuration == action.configuration,
                    SAT_SolverRun.cutoff        >= action.cutoff,
                    )
            query   = session.query(SAT_SolverRun).filter(filter).order_by(sql_random())

            return SAT_Outcome.from_run(query[0])
