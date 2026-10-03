import { useEffect, useRef } from "react";
import { FileLink } from "../../components/FileLink";
import { api } from "../../api/client";
import { PipelineEditor } from "../../components/PipelineEditor";
import { SignedInAs } from "../../components/SignedInAs";
import { RunProgress } from "../../components/RunProgress";
import { ACTIVE_STATUSES } from "../../lib/runs";
import { jobLabel, jobRunType, type Job } from "../../lib/jobs";
import type { StageState } from "../../lib/stagedFlow";
import type { RunManifest } from "../../types";
import { useRunManifest } from "./useRunManifest";

export interface JobStatus { status: StageState; counts: string | null }

function statusOf(run: RunManifest | null): JobStatus {
  if (!run || ACTIVE_STATUSES.has(run.status)) return { status: "running", counts: run ? `${run.completed_count}/${run.company_count}` : null };
  const counts = `${run.completed_count}/${run.company_count}`;
  if (run.status === "completed") return { status: "done", counts };
  if (run.status === "cancelled") return { status: "review", counts };
  if (run.status === "failed") return { status: "failed", counts };
  return { status: "review", counts };
}

/** One job's run progress, pipeline editor (restart) and CSV export; reports its status upward when it changes. */
export function JobRun(p: { job: Job; runId: string; onRestarted: (runId: string) => void; onStatus: (s: JobStatus) => void }) {
  const { job, runId, onRestarted, onStatus } = p;
  const run = useRunManifest(runId);
  const { status, counts } = statusOf(run);
  const last = useRef<JobStatus | null>(null);
  const report = useRef(onStatus);
  report.current = onStatus;
  useEffect(() => {
    if (last.current?.status === status && last.current.counts === counts) return;
    last.current = { status, counts };
    report.current({ status, counts });
  }, [status, counts]);
  return (
    <section className="card">
      <h2>{jobLabel(job)}: run progress</h2>
      <RunProgress runId={runId} runType={jobRunType(job)} />
      <PipelineEditor key={runId} profile={job.profile} runId={runId} onRestarted={onRestarted} />
      <div className="toolbar">
        <FileLink url={api.exportRunCsvUrl(runId)} name={`${runId}.csv`}>
          Export CSV
        </FileLink>
        <SignedInAs compact />
      </div>
    </section>
  );
}
