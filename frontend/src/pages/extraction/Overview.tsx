import type { JSX } from "react";
import { PipelineEditor } from "../../components/PipelineEditor";
import { TransitionPlanMethodology } from "../../components/TransitionPlanResults";
import { PROFILE_META, type Job } from "../../lib/jobs";
import type { ExtractionProfile } from "../../types";

const ORDER: ExtractionProfile[] = ["custom", "financials", "tnfd", "transition_plan"];

/** The landing tab: profile picker, flow chart, scoring summary, current runs and the selected run's steps per company. */
export function Overview(p: {
  jobs: Job[];
  onToggle: (profile: ExtractionProfile) => void;
  pickerError: string | null;
  allAuto: boolean;
  onAllAuto: (on: boolean) => void;
  chart: JSX.Element;
  runs: JSX.Element;
  selectedRunId: string | null;
  selectedProfile: ExtractionProfile | null;
  onRestarted?: (runId: string) => void;
  scoring: JSX.Element;
}) {
  const ticked = (id: ExtractionProfile) => p.jobs.some((j) => j.profile === id);
  return (
    <>
      <section className="card">
        <h2>Profiles</h2>
        <fieldset className="profile-picker">
          <legend className="visually-hidden">Extraction profiles</legend>
          {ORDER.map((id) => (
            <label key={id} className="profile-option">
              <input type="checkbox" checked={ticked(id)} onChange={() => p.onToggle(id)} />
              <span>
                <strong>{PROFILE_META[id].label}</strong>
                <span className="help-text">{PROFILE_META[id].about}</span>
              </span>
            </label>
          ))}
        </fieldset>
        {p.pickerError && <p className="error-text" role="alert">{p.pickerError}</p>}
        <label className="checkbox-label">
          <input type="checkbox" checked={p.allAuto} onChange={(e) => p.onAllAuto(e.target.checked)} />
          Run all automatically
        </label>
        {ticked("transition_plan") && <TransitionPlanMethodology />}
      </section>
      {p.chart}
      {p.scoring}
      {p.runs}
      {p.selectedRunId && p.selectedProfile && (
        <section className="card">
          <h2>Steps per company</h2>
          <PipelineEditor key={p.selectedRunId} profile={p.selectedProfile} runId={p.selectedRunId} onRestarted={p.onRestarted} />
        </section>
      )}
    </>
  );
}
