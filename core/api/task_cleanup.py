from __future__ import annotations

"""Per-task cleanup helpers."""

import os

from ..extraction_types import EmbeddedExtractionResult
from ..workspace import TaskPlan, dedupe_paths
from ..workflow.publish import promote_output_dir_contents
from .delete_service import build_delete_request, delete_artifacts, merge_delete_requests
from .models import DeleteRequest, DeleteResult, ExtractOptions
from .options import normalize_delete_options


def finalize_task_cleanup(
    *,
    plan: TaskPlan,
    extraction_result: EmbeddedExtractionResult,
    options: ExtractOptions,
) -> tuple[DeleteResult, DeleteRequest]:
    """Finalize promotion and cleanup for one extraction task."""

    cleanup_messages: list[str] = []
    moved_paths: list[str] = []
    removed_paths: list[str] = []
    failed_paths: list[str] = []
    skipped_paths: list[str] = []

    source_delete_request = build_delete_request(
        extraction_result.source_paths if options.delete_source_archives else [],
        source_cleanup_root=plan.workspace_dir,
    )
    working_dir_delete_request = build_delete_request(
        [],
        working_dirs=[extraction_result.working_dir]
        if options.delete_working_dir and extraction_result.working_dir
        else [],
        source_cleanup_root=plan.workspace_dir,
    )

    promotion_succeeded = True
    if options.promote_output_contents_to_workspace and extraction_result.extracted_files:
        promotion = promote_output_dir_contents(
            workspace_dir=plan.workspace_dir,
            output_dir_name=os.path.basename(plan.output_dir),
        )
        moved_paths.extend(promotion.moved_paths)
        removed_paths.extend(promotion.removed_paths)
        cleanup_messages.extend(promotion.errors)
        promotion_succeeded = promotion.success
        if promotion.success:
            extraction_result.extracted_files = promotion.moved_paths
        else:
            failed_paths.append(plan.output_dir)

    if promotion_succeeded:
        source_cleanup = delete_artifacts(
            source_delete_request,
            normalize_delete_options({"use_recycle_bin": options.use_recycle_bin}),
        )
        cleanup_messages.extend(source_cleanup.messages)
        removed_paths.extend(source_cleanup.removed_paths)
        failed_paths.extend(source_cleanup.failed_paths)
        skipped_paths.extend(source_cleanup.skipped_paths)

        working_cleanup = delete_artifacts(
            working_dir_delete_request,
            normalize_delete_options({"use_recycle_bin": options.use_recycle_bin}),
        )
        cleanup_messages.extend(working_cleanup.messages)
        removed_paths.extend(working_cleanup.removed_paths)
        failed_paths.extend(working_cleanup.failed_paths)
        skipped_paths.extend(working_cleanup.skipped_paths)
    else:
        if source_delete_request.source_paths:
            cleanup_messages.append("已跳过源文件删除：提取结果回填失败，保留源文件以避免数据丢失。")
        if working_dir_delete_request.working_dirs:
            cleanup_messages.append("已跳过工作目录清理：提取结果回填失败，保留中间结果以便排查。")

    delete_request = merge_delete_requests(source_delete_request, working_dir_delete_request)
    return (
        DeleteResult(
            removed_paths=dedupe_paths(removed_paths),
            moved_paths=dedupe_paths(moved_paths),
            skipped_paths=dedupe_paths(skipped_paths),
            failed_paths=dedupe_paths(failed_paths),
            messages=list(dict.fromkeys(cleanup_messages)),
        ),
        delete_request,
    )
