export function BatchToggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="checkbox-label">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      Batch (50% cheaper, slower)
    </label>
  );
}
