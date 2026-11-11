/** "move to collection…": a select whose options are the valid targets ("" = Unsorted). Picking
 *  one fires `onPick` once; the select then returns to its placeholder. */
export function MoveToCollection({ targets, disabled, onPick }: { targets: string[]; disabled: boolean; onPick: (to: string) => void }) {
  return (
    <select className="move-coll" value="__none" disabled={disabled} aria-label="move to collection"
      title="Move to another collection on the same volume (a rename; nothing is copied)"
      onChange={(e) => { if (e.target.value !== "__none") onPick(e.target.value); }}>
      <option value="__none" disabled>move to collection…</option>
      {targets.map((t) => <option key={t || "(unsorted)"} value={t}>{t || "Unsorted"}</option>)}
    </select>
  );
}
