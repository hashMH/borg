"""
@author: Bryan Silverthorn <bcs@cargo-cult.org>
"""

from uuid                       import (
    UUID,
    uuid4,
    )
from sqlalchemy                 import (
    Enum,
    Table,
    Column,
    String,
    Integer,
    Boolean,
    ForeignKey,
    LargeBinary,
    )
from sqlalchemy.orm             import (
    relationship,
    )
from sqlalchemy.ext.declarative import declarative_base
from cargo.log                  import get_logger
from cargo.sql.alchemy          import (
    SQL_UUID,
    SQL_Engines,
    UTC_DateTime,
    SQL_TimeDelta,
    )
from cargo.flags                import (
    Flag,
    Flags,
    )

log          = get_logger(__name__)
DatumBase    = declarative_base()
module_flags = \
    Flags(
        "Research Data Storage",
        Flag(
            "--research-database",
            default = "sqlite:///:memory:",
            metavar = "DATABASE",
            help    = "use research DATABASE by default [%default]",
            ),
        Flag(
            "--create-research-schema",
            action  = "store_true",
            help    = "create the research data schema, if necessary",
            ),
        )

def research_connect(engines = SQL_Engines.default, flags = module_flags.given):
    """
    Connect to research data storage.
    """

    flags  = module_flags.merged(flags)
    engine = engines.get(flags.research_database)

    if flags.create_research_schema:
        DatumBase.metadata.create_all(engine)

    return engine

class CPU_LimitedRunRow(DatumBase):
    """
    Information about a CPU-limited run of some program.
    """

    __tablename__ = "cpu_limited_runs"

    uuid          = Column(SQL_UUID, primary_key = True, default = uuid4)
    started       = Column(UTC_DateTime)
    usage_elapsed = Column(SQL_TimeDelta)
    proc_elapsed  = Column(SQL_TimeDelta)
    cutoff        = Column(SQL_TimeDelta)
    fqdn          = Column(String)
    stdout        = Column(LargeBinary)
    stderr        = Column(LargeBinary)
    exit_status   = Column(Integer)
    exit_signal   = Column(Integer)

    @staticmethod
    def from_run(run, **kwargs):
        """
        Create a row from a run instance.
        """

        row = \
            CPU_LimitedRunRow(
                started       = run.started,
                usage_elapsed = run.usage_elapsed,
                proc_elapsed  = run.proc_elapsed,
                cutoff        = run.limit,
                exit_status   = run.exit_status,
                exit_signal   = run.exit_signal,
                **kwargs
                )

        row.set_stdout("".join(c for (_, c) in run.out_chunks))
        row.set_stderr("".join(c for (_, c) in run.err_chunks))

        return row

    def get_stdout(self):
        """
        Get stdout text, uncompressed.
        """

        from cargo.io import unxzed

        return unxzed(self.stdout)

    def set_stdout(self, stdout):
        """
        Set stdout text, compressing.
        """

        from cargo.io import xzed

        self.stdout = xzed(stdout)

    def get_stderr(self):
        """
        Get stderr text, uncompressed.
        """

        from cargo.io import unxzed

        return unxzed(self.stderr)

    def set_stderr(self, stderr):
        """
        Set stderr text, compressing.
        """

        from cargo.io import xzed

        self.stderr = xzed(stderr)

class SolverRow(DatumBase):
    """
    Some solver for some domain.
    """

    __tablename__ = "solvers"

    name = Column(String, primary_key = True)
    type = Column(String)

    def get_solver(self):
        """
        Get the solver associated with this solver row.
        """

        from utexas.sat.solvers import LookupSolver

        return LookupSolver(self.name)

class TrialRow(DatumBase):
    """
    A set of [sets of [...]] attempts.
    """

    RECYCLABLE_UUID = UUID("777d15f0-b1cd-4c89-9bf9-814d0974c748")

    __tablename__ = "trials"

    uuid        = Column(SQL_UUID, primary_key = True, default = uuid4)
    parent_uuid = Column(SQL_UUID, ForeignKey("trials.uuid"))
    label       = Column(String)

    @staticmethod
    def get_recyclable(session):
        """
        Retrieve the core "recyclable" trial.
        """

        return                                                 \
            session                                            \
            .query(TrialRow)                                   \
            .filter(TrialRow.uuid == TrialRow.RECYCLABLE_UUID) \
            .one()

class TaskRow(DatumBase):
    """
    One task.
    """

    __tablename__ = "tasks"
    task_type     = \
        Enum(
            "file",
            "preprocessed",
            name = "task_type",
            )

    uuid = Column(SQL_UUID, primary_key = True, default = uuid4)
    type = Column(task_type)

    __mapper_args__ = {"polymorphic_on": type}

    # backref: "names" from TaskNameRow

    @staticmethod
    def with_prefix(session, prefix, collection = "default"):
        """
        Select tasks with names matching a prefix.
        """

        from sqlalchemy import and_

        return                                            \
            session                                       \
            .query(TaskRow)                               \
            .join(TaskRow.names)                          \
            .filter(
                and_(
                    TaskNameRow.name.startswith(prefix),
                    TaskNameRow.collection == collection,
                    ),
                )                                         \
            .all()

class FileTaskRow(TaskRow):
    """
    Tasks backed by files.
    """

    __tablename__   = "file_tasks"
    __mapper_args__ = {"polymorphic_identity": "file"}

    uuid = Column(SQL_UUID, ForeignKey("tasks.uuid"), primary_key = True)
    hash = Column(LargeBinary(length = 64), unique = True)

    def get_task(self, environment):
        """
        Build a task from this task row.
        """

        # find a path for this task, if one exists
        task_path = None

        for name_row in self.names:
            root = environment.collections.get(name_row.collection)

            if root is not None:
                task_path = join(root, name_row.name)

                break

        # if possible, build and return the task
        if task_path is None:
            raise RuntimeError("could not find a usable name for this task")
        else:
            from utexas.sat.tasks import FileTask

            return FileTask(tasks_path, row = self)

class PreprocessedTaskRow(TaskRow):
    """
    One task after preprocessing.
    """

    __tablename__ = "preprocessed_tasks"

    uuid              = Column(SQL_UUID, ForeignKey(TaskRow.uuid), primary_key = True)
    preprocessor_name = Column(String, ForeignKey("solvers.name"), nullable = False)
    seed              = Column(Integer)
    input_task_uuid   = Column(SQL_UUID, ForeignKey("tasks.uuid"), nullable = False)

    __mapper_args__ = {
        "polymorphic_identity" : "preprocessed",
        "inherit_condition"    : uuid == TaskRow.uuid,
        }

    preprocessor = relationship(SolverRow)
    input_task   = \
        relationship(
            TaskRow,
            primaryjoin = (input_task_uuid == TaskRow.uuid),
            )

    def get_task(self, environment):
        """
        Build a task from this task row.
        """

        # find the corresponding output directory, if it exists
        from os import isdir

        root        = environment.collections[None]
        output_path = join(root, self.uuid.hex)

        if not isdir(output_path):
            raise RuntimeError("no corresponding directory exists for task")

        # build and return the task
        preprocessor = self.preprocessor.get_solver()
        input_task   = self.input_task.get_task(environment)

        return preprocessor.make_task(self.seed, input_task, output_path, environment, self)

class TaskNameRow(DatumBase):
    """
    Place a task in the context of a collection.
    """

    __tablename__ = "task_names"

    uuid       = Column(SQL_UUID, primary_key = True, default = uuid4)
    task_uuid  = Column(SQL_UUID, ForeignKey("tasks.uuid"), nullable = False)
    name       = Column(String)
    collection = Column(String)

    task = relationship(TaskRow, backref = "names")

class AnswerRow(DatumBase):
    """
    An answer to a task.
    """

    __tablename__ = "answers"
    answer_type   = \
        Enum(
            "sat",
            name = "answer_type",
            )

    uuid = Column(SQL_UUID, primary_key = True, default = uuid4)
    type = Column(answer_type)

    __mapper_args__ = {"polymorphic_on": type}

class SAT_AnswerRow(AnswerRow):
    """
    Answer to a SAT instance.
    """

    __tablename__   = "sat_answers"
    __mapper_args__ = {"polymorphic_identity": "sat"}

    uuid           = Column(SQL_UUID, ForeignKey("answers.uuid"), primary_key = True, default = uuid4)
    satisfiable    = Column(Boolean)
    certificate_xz = Column(LargeBinary)

    def __init__(self, satisfiable = None, certificate = None, certificate_xz = None):
        """
        Initialize.
        """

        # argument sanity
        if certificate is not None and certificate_xz is not None:
            raise ValueError("cannot specify both certificate and compressed certificate")

        # members
        if certificate is not None:
            certificate_xz = SAT_AnswerRow.pack_certificate(certificate)

        # base
        AnswerRow.__init__(
            self,
            satisfiable    = satisfiable,
            certificate_xz = certificate_xz,
            )

    def get_certificate(self):
        """
        Get the certificate array, uncompressed.
        """

        if self.certificate_xz is None:
            return None
        else:
            return SAT_AnswerRow.unpack_certificate(self.certificate_xz)

    def set_certificate(self, certificate):
        """
        Set (and compress) the certificate array.
        """

        self.certificate_xz = SAT_AnswerRow.pack_certificate(certificate)

    @staticmethod
    def pack_certificate(certificate):
        """
        Set (and compress) the certificate array.
        """

        import json

        from cargo.io import xzed

        return xzed(json.dumps(certificate))

    @staticmethod
    def unpack_certificate(blob):
        """
        Uncompress and interpret a certificate array.
        """

        import json

        from cargo.io import unxzed

        return json.loads(unxzed(blob))

attempts_trials_table = \
    Table(
        "attempts_trials",
        DatumBase.metadata,
        Column("attempt_uuid", SQL_UUID, ForeignKey("attempts.uuid")),
        Column("trial_uuid", SQL_UUID, ForeignKey("trials.uuid")),
        )

class AttemptRow(DatumBase):
    """
    An attempt to solve a task.
    """

    __tablename__ = "attempts"
    attempt_type  =\
        Enum(
            "run",
            "preprocessing",
            name = "attempt_type",
            )

    uuid        = Column(SQL_UUID, primary_key = True, default = uuid4)
    type        = Column(attempt_type)
    budget      = Column(SQL_TimeDelta)
    cost        = Column(SQL_TimeDelta)
    task_uuid   = Column(SQL_UUID, ForeignKey("tasks.uuid"))
    answer_uuid = Column(SQL_UUID, ForeignKey("answers.uuid"))

    __mapper_args__ = {"polymorphic_on": type}

    task   = relationship(TaskRow)
    answer = relationship(AnswerRow)
    trials = \
        relationship(
            TrialRow,
            secondary = attempts_trials_table,
            backref   = "attempts",
            )

class RunAttemptRow(AttemptRow):
    """
    An attempt to solve a task with a concrete solver.
    """

    __tablename__   = "run_attempts"
    __mapper_args__ = {"polymorphic_identity": "run"}

    uuid        = Column(SQL_UUID, ForeignKey("attempts.uuid"), primary_key = True)
    solver_name = Column(String, ForeignKey("solvers.name"), nullable = False)
    seed        = Column(Integer)
    run_uuid    = Column(SQL_UUID, ForeignKey("cpu_limited_runs.uuid"), nullable = False)

    run    = relationship(CPU_LimitedRunRow)
    solver = relationship(SolverRow)

class PreprocessingAttemptRow(RunAttemptRow):
    """
    Execution of a preprocessor on a task.
    """

    __tablename__ = "preprocessing_attempts"
    __mapper_args__ = {"polymorphic_identity": "preprocessing"}

    uuid              = Column(SQL_UUID, ForeignKey("run_attempts.uuid"), primary_key = True, default = uuid4)
    output_task_uuid  = Column(SQL_UUID, ForeignKey("tasks.uuid"), nullable = False)

    output_task = \
        relationship(
            TaskRow,
            primaryjoin = (TaskRow.uuid == output_task_uuid),
            )
