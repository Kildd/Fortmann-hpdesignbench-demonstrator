export type GeometryState = {
  span_mm?: number
  b_mm?: number
  h_ges_mm?: number
  hx_mm?: number
  hy_mm?: number
  hx_hges_ratio?: number
  t_mm?: number
  nt?: number
  dy_mm?: number
  t_infill_mm?: number
  t_screed_mm?: number
  t_insulation_mm?: number
  fck?: number
  kap_t_percent?: number
  a_tex_mm2?: number
}

export type BestState = {
  trial: number
  y: number
  y_p: number
  vars: Record<string, number | string>
  penalties: Record<string, number>
  utilizations: Record<string, number>
  geometry: GeometryState
  is_feasible: boolean
}

export type StartEvent = {
  type: 'start'
  n_trials: number
  var_names: string[]
  var_labels: Record<string, string>
  constraint_labels: Record<string, string>
  omega_gwp: number
  omega_cost: number
  integrator?: string
}

export type TrialEvent = {
  type: 'trial'
  trial: number
  x: number[]
  vars: Record<string, number | string>
  y: number | null
  y_p: number | null
  penalties: Record<string, number>
  utilizations: Record<string, number>
  error: string | null
  geometry: GeometryState
  is_feasible: boolean
  /** New penalized best (internal optimizer metric y_p). */
  is_best: boolean
  best: BestState | null
  /** New best among feasible designs by physical y. */
  is_best_feasible: boolean
  bestFeasible: BestState | null
}

export type DoneEvent = {
  type: 'done'
  best: BestState | null
  bestFeasible: BestState | null
  n_trials: number
  best_value: number | null
}

export type ErrorEvent = {
  type: 'error'
  message: string
}

export type StatusEvent = {
  type: 'status'
  message: string
}

export type ReadyEvent = {
  type: 'ready'
}

export type OptEvent =
  | StartEvent
  | TrialEvent
  | DoneEvent
  | ErrorEvent
  | StatusEvent
  | ReadyEvent

export type OptimizeRequest = {
  nTrials: number
  omegaGwp: number
  omegaCost: number
  spanMm: number
  loadCategory: string
  seed: number
}
