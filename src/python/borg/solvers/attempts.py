"""
@author: Bryan Silverthorn <bcs@cargo-cult.org>
"""

from abc        import abstractproperty
from borg.rowed import (
    Rowed,
    AbstractRowed,
    )

class AbstractAttempt(AbstractRowed):
    """
    Abstract base of the outcome of a solver's attempt on a task.
    """

    @abstractproperty
    def solver(self):
        """
        The solver that obtained this result.
        """

    @abstractproperty
    def budget(self):
        """
        The budget provided to the solver to obtain this result.
        """

    @abstractproperty
    def cost(self):
        """
        The cost of obtaining this result.
        """

    @abstractproperty
    def task(self):
        """
        The task on which this result was obtained.
        """

    @abstractproperty
    def answer(self):
        """
        The answer obtained by the solver, if any.
        """

class AbstractRunAttempt(AbstractAttempt):
    """
    Abstract base of a binary solver's attempt.
    """

    @abstractproperty
    def seed(self):
        """
        The PRNG seed used for the run.
        """

    @abstractproperty
    def run(self):
        """
        The details of the run.
        """

class AbstractPreprocessingAttempt(AbstractRunAttempt):
    """
    The result of running a preprocessor.
    """

    @abstractproperty
    def output_task(self):
        """
        The task generated by the preprocessor, if any.
        """

class Attempt(Rowed, AbstractAttempt):
    """
    The outcome of a solver's attempt on a task.
    """

    def __init__(self, solver, budget, cost, task, answer):
        """
        Initialize.
        """

        Rowed.__init__(self)

        self._solver = solver
        self._budget = budget
        self._cost   = cost
        self._task   = task
        self._answer = answer

    def get_new_row(self, session):
        """
        Create or obtain an ORM row for this object.
        """

        from borg.data import AttemptRow

        return self._get_new_row(session, AttemptRow)

    def _get_new_row(self, session, Row, **kwargs):
        """
        Create or obtain an ORM row for this object.
        """

        from borg.data import SAT_AnswerRow

        if self.answer is None:
            answer_row = None
        else:
            answer_row = \
                SAT_AnswerRow(
                    satisfiable = self.answer.satisfiable,
                    certificate = self.answer.certificate,
                    )

        attempt_row = \
            Row(
                budget = self.budget,
                cost   = self.cost,
                task   = self.task.get_row(session),
                answer = answer_row,
                **kwargs
                )

        session.add(attempt_row)

        return attempt_row

    @property
    def solver(self):
        """
        The solver which obtained this result.
        """

        return self._solver

    @property
    def budget(self):
        """
        The budget provided to the solver to obtain this result.
        """

        return self._budget

    @property
    def cost(self):
        """
        The cost of obtaining this result.
        """

        return self._cost

    @property
    def task(self):
        """
        The task on which this result was obtained.
        """

        return self._task

    @property
    def answer(self):
        """
        The answer obtained by the solver, if any.
        """

        return self._answer

class WrappedAttempt(Rowed, AbstractAttempt):
    """
    The wrapped outcome of a solver.
    """

    def __init__(self, solver, inner):
        """
        Initialize.
        """

        # argument sanity
        assert isinstance(inner, AbstractAttempt)

        # members
        self._solver = solver
        self._inner  = inner

    def get_new_row(self, session, solver_row = None):
        """
        Return a database description of this result.
        """

        if solver_row is None:
            solver_row = self._solver.get_row(session)

        return self._inner.get_row(session, solver_row = solver_row)

    @property
    def solver(self):
        """
        The solver which obtained this result.
        """

        return self._solver

    @property
    def budget(self):
        """
        The budget provided to the solver to obtain this result.
        """

        return self._inner.budget

    @property
    def cost(self):
        """
        The cost of obtaining this result.
        """

        return self._inner.cost

    @property
    def task(self):
        """
        The task on which this result was obtained.
        """

        return self._inner.task

    @property
    def answer(self):
        """
        The answer obtained by the solver, if any.
        """

        return self._inner.answer

class RunAttempt(Attempt):
    """
    Outcome of an external SAT solver binary.
    """

    def __init__(self, solver, task, answer, seed, run):
        """
        Initialize.
        """

        Attempt.__init__(
            self,
            solver,
            run.limit,
            run.proc_elapsed,
            task,
            answer,
            )

        self._seed = seed
        self._run  = run

    def get_new_row(self, session, solver_row = None):
        """
        Return a database description of this result.
        """

        from borg.data import RunAttemptRow

        return self._get_new_row(session, RunAttemptRow, solver_row = solver_row)

    def _get_new_row(self, session, Row, solver_row = None, **kwargs):
        """
        Create or obtain an ORM row for this object.
        """

        if solver_row is None:
            solver_row = self._solver.get_row(session)

        return \
            Attempt._get_new_row(
                self,
                session,
                Row,
                solver = solver_row,
                seed   = self._seed,
                run    = CPU_LimitedRunRow.from_run(self._run),
                )

    @property
    def seed(self):
        """
        The PRNG seed used for the run.
        """

        return self._seed

    @property
    def run(self):
        """
        The details of the run.
        """

        return self._run

class WrappedRunAttempt(WrappedAttempt):
    """
    The wrapped outcome of a solver.
    """

    def __init__(self, solver, inner):
        """
        Initialize.
        """

        # argument sanity
        assert isinstance(inner, AbstractRunAttempt)

        # base
        WrappedAttempt.__init__(self, solver, inner)

    @property
    def seed(self):
        """
        The PRNG seed used for the run.
        """

        return self._inner.seed

    @property
    def run(self):
        """
        The details of the run.
        """

        return self._inner.run

class PreprocessingAttempt(RunAttempt, AbstractPreprocessingAttempt):
    """
    The result of a preprocessor.
    """

    def __init__(self, preprocessor, input_task, answer, seed, run, output_task):
        """
        Initialize.
        """

        RunAttempt.__init__(
            self,
            preprocessor,
            input_task,
            answer,
            seed,
            run,
            )

        self._output_task = output_task

    def get_new_row(self, session, solver_row = None):
        """
        Return a database description of this result.
        """

        from borg.data import PreprocessingAttemptRow

        return self._get_new_row(session, PreprocessingAttemptRow, solver_row = solver_row)

    def _get_new_row(self, session, Row, **kwargs):
        """
        Create or obtain an ORM row for this object.
        """

        return \
            RunAttempt._get_new_row(
                self,
                session,
                Row,
                output_task = self._output_task.get_row(session),
                **kwargs
                )

    @property
    def output_task(self):
        """
        The task generated by the preprocessor, if any.
        """

        return self._output_task

class WrappedPreprocessingAttempt(WrappedRunAttempt, AbstractPreprocessingAttempt):
    """
    The wrapped outcome of a preprocessor.
    """

    def __init__(self, preprocessor, inner):
        """
        Initialize.
        """

        # argument sanity
        assert isinstance(inner, AbstractPreprocessingAttempt)

        # base
        WrappedRunAttempt.__init__(self, preprocessor, inner)

    @property
    def output_task(self):
        """
        The task generated by the preprocessor, if any.
        """

        return self._inner.output_task

