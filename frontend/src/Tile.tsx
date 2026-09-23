/**
 * Плитка с одним числом.
 *
 * Вынесена из `Dashboard.tsx`, когда такие же понадобились панели
 * разметки: две копии разошлись бы в оформлении, и один и тот же
 * показатель выглядел бы на соседних панелях по-разному.
 */

export type Tone = 'good' | 'bad' | 'warn'

export default function Tile({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: string
  note?: string
  tone?: Tone
}) {
  return (
    <div className={tone ? `tile ${tone}` : 'tile'}>
      <span className="tile-label">{label}</span>
      <strong className="tile-value">{value}</strong>
      {note && <span className="tile-note">{note}</span>}
    </div>
  )
}
