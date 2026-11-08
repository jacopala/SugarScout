import { useMeals, type Meal } from '../lib/queries'
import { SparkleIcon } from './Icons'

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })
const SOURCE: Record<Meal['source'], string> = { voice: 'said by voice', tap: 'tapped', text: 'typed' }

function MealTags({ meal }: { meal: Meal }) {
  if (meal.analysis_status === 'pending') return <span className="tag">Estimating…</span>
  if (meal.analysis_status !== 'ok' || !meal.analysis) {
    return <span className="tag">No estimate{meal.analysis_status === 'disabled' ? ' (AI off)' : ''}</span>
  }
  const a = meal.analysis
  return (
    <>
      {a.total_carbs_g !== undefined ? <span className="tag carbs">Carbs ~{Math.round(a.total_carbs_g)} g</span> : null}
      <span className="tag sugar">Sugar ~{Math.round(a.total_sugar_g)} g</span>
      {a.contains_gluten ? <span className="tag gluten">Contains gluten</span> : <span className="tag gf">Gluten-free</span>}
      {a.confidence === 'low' ? <span className="tag">Rough guess</span> : null}
    </>
  )
}

/** Parent view of what the child reported eating, with AI sugar/gluten estimates. */
export function MealsCard() {
  const { data } = useMeals(1)
  const meals = data ?? []
  const estimated = meals.filter((m) => m.analysis_status === 'ok' && m.analysis)
  const sugar = estimated.reduce((s, m) => s + (m.analysis?.total_sugar_g ?? 0), 0)
  const carbs = estimated.reduce((s, m) => s + (m.analysis?.total_carbs_g ?? 0), 0)
  const gluten = estimated.filter((m) => m.analysis?.contains_gluten).length

  return (
    <section className="card" aria-labelledby="meals-h">
      <h2 id="meals-h">Meals &amp; intake today</h2>
      {meals.length === 0 ? (
        <p className="empty">No meals reported yet. Alex can tell Scout from the Meals button.</p>
      ) : (
        <>
          <div className="meal-totals">
            <div className="meal-total carbs">
              <span>Carbs (est.)</span>
              <strong>~{Math.round(carbs)} g</strong>
            </div>
            <div className="meal-total sugar">
              <span>Sugar (est.)</span>
              <strong>~{Math.round(sugar)} g</strong>
            </div>
            <div className="meal-total gluten">
              <span>Gluten</span>
              <strong>
                {gluten} of {estimated.length || meals.length}
              </strong>
            </div>
          </div>
          <p className="ai-note">
            <SparkleIcon size={16} color="#7766C6" />
            AI estimate from what Alex said or tapped. Not a carb count for dosing: always check the label or your plan.
          </p>
          <ul className="meal-list">
            {meals.map((m) => (
              <li key={m.id} className="meal-row">
                <div className="meal-row-meta">
                  <time dateTime={m.created_at}>{timeFmt.format(new Date(m.created_at))}</time>
                  <span>{SOURCE[m.source]}</span>
                </div>
                <span className="meal-row-desc">“{m.description}”</span>
                <div className="tags">
                  <MealTags meal={m} />
                  {m.glucose_1h !== null ? <span className="tag">Glucose 1 h later: {m.glucose_1h}</span> : null}
                </div>
                {m.analysis?.note ? <span className="section-note" style={{ margin: 0 }}>{m.analysis.note}</span> : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
