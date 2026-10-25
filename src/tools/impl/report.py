from src.schemas.tools import GenerateReportArgs
from src.tools.impl.base import ToolContext, ToolError


def generate_report(args: GenerateReportArgs, ctx: ToolContext) -> dict:
    if args.run_id != ctx.state.run_id:
        raise ToolError("invalid_arguments", "run_id does not match the active run", "run_id")
    if ctx.report_builder is None:
        raise ToolError("not_ready", "report builder not attached to this run")
    return ctx.report_builder(args.sections)  # raises ToolError on empty mandatory sections
