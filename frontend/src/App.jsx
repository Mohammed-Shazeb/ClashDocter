import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { WarningCircle } from '@phosphor-icons/react';
import { api } from './services/api.js';
import { clearSession, loadSession, saveSession } from './session.js';
import ModeBanner from './components/ModeBanner.jsx';
import ImportPanel from './components/ImportPanel.jsx';
import LineupEditor from './components/LineupEditor.jsx';
import ScheduleGrid from './components/ScheduleGrid.jsx';
import SimilarityHeatmap from './components/SimilarityHeatmap.jsx';
import PairEvidence from './components/PairEvidence.jsx';
import ClashSummary from './components/ClashSummary.jsx';
import OptimizePanel from './components/OptimizePanel.jsx';
import PlanningPanel from './components/PlanningPanel.jsx';
import SimilarityError from './components/SimilarityError.jsx';
import AsciiConcertIntro from './components/AsciiConcertIntro.jsx';

function pathnameToRoute(pathname) {
  const clean = (pathname || '/').replace(/\/+$/, '') || '/';
  return clean === '/dashboard' ? 'dashboard' : 'intro';
}

function SectionTitle({ index, title, aside }) {
  return (
    <div className="section-head">
      <h2 className="section-title">
        <span className="section-index">{index}</span>
        {title}
      </h2>
      {aside && <span className="section-aside">{aside}</span>}
    </div>
  );
}

const PREFERENCE_KEYS = [
  'high_affinity_threshold',
  'high_affinity_weight',
  'move_penalty',
  'max_moves',
];

const DEFAULT_PREFERENCES = {
  high_affinity_threshold: 0.4,
  high_affinity_weight: 1,
  move_penalty: 0,
  max_moves: 200,
};

export default function App() {
  const [health, setHealth] = useState(null);
  const [festival, setFestival] = useState(null); // {stages, slots, acts, mode, name}
  const [similarity, setSimilarity] = useState(null); // {profiles, pairs, mode}
  const [analysis, setAnalysis] = useState(null); // OptimizeResponse for current acts
  const [preferences, setPreferences] = useState(DEFAULT_PREFERENCES);
  const [applied, setApplied] = useState(false);
  const [applying, setApplying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [structureBusy, setStructureBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);
  const [plan, setPlan] = useState(null); // PlanInterpretResponse for the current lineup
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState(null);
  const [planRunning, setPlanRunning] = useState(false);
  const [lockSources, setLockSources] = useState({}); // act id → 'organizer' | 'planner'
  const [scheduleError, setScheduleError] = useState(null);
  const [similarityError, setSimilarityError] = useState(null);
  const [similarityBusy, setSimilarityBusy] = useState(false);
  // Minimal History-API routing: '/' shows the concert intro, '/dashboard'
  // the application. Anything else falls back to the intro at '/'.
  const [route, setRoute] = useState(() => pathnameToRoute(window.location.pathname));

  useEffect(() => {
    const raw = window.location.pathname;
    const clean = (raw || '/').replace(/\/+$/, '') || '/';
    if (clean !== raw) {
      window.history.replaceState(null, '', clean);
    } else if (pathnameToRoute(clean) === 'intro' && clean !== '/') {
      window.history.replaceState(null, '', '/');
    }
    const onPopState = () => setRoute(pathnameToRoute(window.location.pathname));
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const goDashboard = useCallback(() => {
    window.history.pushState(null, '', '/dashboard');
    setRoute('dashboard');
  }, []);

  const analysisSeq = useRef(0);
  const planSeq = useRef(0);
  const similaritySeq = useRef(0);
  const pristineDemo = useRef(null); // a freshly loaded demo is not a working session

  const acts = festival?.acts ?? [];

  const clearPlan = useCallback(() => {
    planSeq.current += 1; // drop any in-flight interpretation for the previous lineup
    setPlan(null);
    setPlanError(null);
    setPlanning(false);
  }, []);

  const runAnalysis = useCallback(async (festivalData, prefs) => {
    if (!festivalData || !festivalData.acts.length) return null;
    const sequence = ++analysisSeq.current;
    setAnalyzing(true);
    try {
      const result = await api.optimize(
        festivalData.stages,
        festivalData.slots,
        festivalData.acts,
        prefs,
      );
      if (sequence !== analysisSeq.current) return null;
      setError(null);
      return result;
    } catch (err) {
      if (sequence !== analysisSeq.current) return null;
      setError({ source: 'analysis', message: err.message, code: err.code });
      return null;
    } finally {
      if (sequence === analysisSeq.current) setAnalyzing(false);
    }
  }, []);

  const loadDemo = useCallback(async () => {
    // Resetting the demo is an explicit reset: the persisted session must not
    // bring the old lineup back on the next refresh.
    clearSession();
    setLoading(true);
    setError(null);
    setNotice(null);
    setApplied(false);
    setPreferences(DEFAULT_PREFERENCES);
    setLockSources({});
    setScheduleError(null);
    setSimilarityError(null);
    clearPlan();
    analysisSeq.current += 1; // drop any in-flight analysis for the previous lineup
    similaritySeq.current += 1; // and any similarity matrix for it
    try {
      const healthData = await api.health();
      setHealth(healthData);
      const festivalData = await api.demoFestival();
      const entityIds = festivalData.acts.map((a) => a.entity_id);
      const namesMap = Object.fromEntries(
        festivalData.acts.map((a) => [a.entity_id, a.name]),
      );
      // A taste-data failure must not blank the whole app: the seeded schedule
      // still loads, and the similarity section says exactly what failed.
      const [simResult, analysisResult] = await Promise.allSettled([
        api.similarity(entityIds, namesMap),
        api.optimize(festivalData.stages, festivalData.slots, festivalData.acts, DEFAULT_PREFERENCES),
      ]);
      pristineDemo.current = { festival: festivalData };
      setFestival(festivalData);
      if (simResult.status === 'fulfilled') {
        setSimilarity(simResult.value);
      } else {
        setSimilarity(null);
        setSimilarityError({
          message: simResult.reason?.message ?? 'Similarity request failed.',
          artists: festivalData.acts.map((a) => a.name),
        });
      }
      if (analysisResult.status === 'fulfilled') {
        setAnalysis(analysisResult.value);
      } else {
        setError({
          source: 'analysis',
          message: analysisResult.reason?.message ?? 'Optimizer request failed.',
          code: analysisResult.reason?.code,
        });
      }
    } catch (err) {
      setError({ source: 'load', message: err.message, code: err.code });
    } finally {
      setLoading(false);
    }
  }, [clearPlan]);

  useEffect(() => {
    const saved = loadSession();
    if (!saved) {
      loadDemo();
      return;
    }
    setFestival(saved.festival);
    setPreferences(saved.preferences ?? DEFAULT_PREFERENCES);
    setLockSources(saved.lockSources ?? {});
    setApplied(saved.applied);
    setAnalysis(saved.analysis);
    setSimilarity(saved.similarity);
    setLoading(false);
    api.health().then(setHealth).catch(() => {});
  }, [loadDemo]);

  useEffect(() => {
    if (!festival) return;
    const base = pristineDemo.current;
    const isPristineDemo =
      base?.festival === festival &&
      !applied &&
      Object.keys(lockSources).length === 0 &&
      PREFERENCE_KEYS.every((key) => Number(preferences[key]) === Number(DEFAULT_PREFERENCES[key]));
    if (isPristineDemo) {
      // Persisting the untouched demo would make "Reset demo" restore an
      // identical copy on refresh instead of starting clean.
      clearSession();
      return;
    }
    saveSession({ festival, preferences, lockSources, applied, analysis, similarity });
  }, [festival, preferences, lockSources, applied, analysis, similarity]);

  const startLive = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotice(null);
    setApplied(false);
    setLockSources({});
    setScheduleError(null);
    setSimilarityError(null);
    clearPlan();
    analysisSeq.current += 1;
    similaritySeq.current += 1;
    try {
      const [healthData, festivalData] = await Promise.all([
        api.health(),
        api.templateFestival(),
      ]);
      setHealth(healthData);
      setFestival(festivalData);
      setSimilarity(null);
      setAnalysis(null);
    } catch (err) {
      setError({ source: 'load', message: err.message, code: err.code });
    } finally {
      setLoading(false);
    }
  }, [clearPlan]);

  const refreshSimilarity = useCallback(async (actsList) => {
    const sequence = ++similaritySeq.current;
    if (!actsList.length) {
      setSimilarity(null);
      setSimilarityError(null);
      return;
    }
    setSimilarityBusy(true);
    try {
      const simData = await api.similarity(
        actsList.map((a) => a.entity_id),
        Object.fromEntries(actsList.map((a) => [a.entity_id, a.name])),
      );
      // Adding and removing acts in quick succession fires one refresh per edit;
      // an older matrix must never replace the newer one the user is waiting for.
      if (sequence !== similaritySeq.current) return;
      setSimilarity(simData);
      setSimilarityError(null);
    } catch (err) {
      if (sequence !== similaritySeq.current) return;
      // Never replace the grid with silent dashes: name the artists the request
      // was for, the reason, and keep a retry within reach.
      setSimilarityError({
        message: err?.message ?? 'Similarity request failed.',
        artists: actsList.map((a) => a.name),
      });
    } finally {
      if (sequence === similaritySeq.current) setSimilarityBusy(false);
    }
  }, []);

  const importFestival = useCallback(
    async ({ name, stages: nextStages, slots: nextSlots, acts: importedActs, unmatched }) => {
      setImporting(true);
      setError(null);
      setNotice(null);
      setApplied(false);
      setLockSources({});
      setScheduleError(null);
      setSimilarityError(null);
      clearPlan();
      try {
        const assigned = await api.assignSchedule(nextStages, nextSlots, importedActs);
        const next = {
          name,
          mode: 'imported',
          stages: nextStages,
          slots: nextSlots,
          acts: assigned.acts,
        };
        setFestival(next);
        setSimilarity(null);
        setAnalysis(null);
        await refreshSimilarity(assigned.acts);
        const result = await runAnalysis(next, preferences);
        if (result) setAnalysis(result);
        setNotice(
          `Imported ${assigned.acts.length} act(s) as “${name}” on ${nextStages.length} stage(s) ` +
            `across ${nextSlots.length} slot(s).` +
            (unmatched
              ? ` ${unmatched} act(s) have no Qloo match and are excluded from scoring.`
              : '') +
            (assigned.note ? ` ${assigned.note}` : ''),
        );
        return true;
      } catch (err) {
        setError({ source: 'import', message: err.message, code: err.code });
        return false;
      } finally {
        setImporting(false);
      }
    },
    [clearPlan, preferences, refreshSimilarity, runAnalysis],
  );

  const updateAct = useCallback(
    async (actId, changes) => {
      if (!festival) return;
      const previousApplied = applied;
      const next = {
        ...festival,
        acts: festival.acts.map((a) => (a.id === actId ? { ...a, ...changes } : a)),
      };
      setApplied(false);
      // A previewed brief describes the lineup it was read from; moving an act to
      // another stage or slot invalidates its locks and its clash assumptions.
      clearPlan();
      setScheduleError(null);
      const sequence = ++analysisSeq.current;
      setAnalyzing(true);
      try {
        // Only commit the edit once the backend has accepted the schedule: an
        // invalid assignment must never reach the grid, not even for a frame.
        const result = await api.optimize(next.stages, next.slots, next.acts, preferences);
        if (sequence !== analysisSeq.current) return;
        setFestival(next);
        setAnalysis(result);
        setError(null);
      } catch (err) {
        if (sequence !== analysisSeq.current) return;
        setApplied(previousApplied);
        if (err.code === 'INVALID_SCHEDULE') {
          const moved = next.acts.find((act) => act.id === actId);
          const occupant = festival.acts.find(
            (act) =>
              act.id !== actId &&
              act.stage_id === moved?.stage_id &&
              act.slot_id === moved?.slot_id,
          );
          setScheduleError({
            message: occupant
              ? `That cell is already occupied by ${occupant.name}. ${err.message}`
              : `That change would make the schedule invalid. ${err.message}`,
            code: err.code,
          });
        } else {
          setError({ source: 'analysis', message: err.message, code: err.code });
        }
      } finally {
        if (sequence === analysisSeq.current) setAnalyzing(false);
      }
    },
    [applied, clearPlan, festival, preferences],
  );

  const toggleActLock = useCallback(
    async (actId) => {
      if (!festival) return;
      const act = festival.acts.find((entry) => entry.id === actId);
      if (!act) return;
      const fixed = !act.fixed;
      const next = {
        ...festival,
        acts: festival.acts.map((entry) =>
          entry.id === actId ? { ...entry, fixed } : entry,
        ),
      };
      setLockSources((prev) => {
        const sources = { ...prev };
        if (fixed) sources[actId] = 'organizer';
        else delete sources[actId];
        return sources;
      });
      setFestival(next);
      setApplied(false);
      clearPlan();
      const result = await runAnalysis(next, preferences);
      if (result) setAnalysis(result);
    },
    [clearPlan, festival, preferences, runAnalysis],
  );

  const clearPlannerLocks = useCallback(async () => {
    if (!festival) return;
    const lockedIds = Object.entries(lockSources)
      .filter(([, source]) => source === 'planner')
      .map(([id]) => id);
    if (!lockedIds.length) return;
    const ids = new Set(lockedIds);
    const next = {
      ...festival,
      acts: festival.acts.map((act) => (ids.has(act.id) ? { ...act, fixed: false } : act)),
    };
    setLockSources((prev) =>
      Object.fromEntries(
        Object.entries(prev).filter(([, source]) => source !== 'planner'),
      ),
    );
    setFestival(next);
    setApplied(false);
    clearPlan();
    const result = await runAnalysis(next, preferences);
    if (result) setAnalysis(result);
  }, [clearPlan, festival, lockSources, preferences, runAnalysis]);

  const addAct = useCallback(
    (candidate, stageId, slotId) => {
      setApplied(false);
      clearPlan();
      setFestival((prev) => {
        const id = `act-${Date.now()}`;
        const newAct = {
          id,
          name: candidate.name,
          entity_id: candidate.entity_id,
          stage_id: stageId,
          slot_id: slotId,
          duration_min: 60,
          fixed: false,
        };
        const next = { ...prev, acts: [...prev.acts, newAct] };
        refreshSimilarity(next.acts);
        runAnalysis(next, preferences).then((result) => {
          if (result) setAnalysis(result);
        });
        return next;
      });
    },
    [clearPlan, preferences, runAnalysis, refreshSimilarity],
  );

  const removeAct = useCallback(
    (actId) => {
      setApplied(false);
      clearPlan();
      setFestival((prev) => {
        const next = { ...prev, acts: prev.acts.filter((a) => a.id !== actId) };
        refreshSimilarity(next.acts);
        if (!next.acts.length) {
          setAnalysis(null);
          return next;
        }
        runAnalysis(next, preferences).then((result) => {
          if (result) setAnalysis(result);
        });
        return next;
      });
    },
    [clearPlan, preferences, runAnalysis, refreshSimilarity],
  );

  const updateStructure = useCallback(
    async (nextStages, nextSlots) => {
      setStructureBusy(true);
      setApplied(false);
      try {
        const payload = acts.map((a) =>
          nextStages.some((s) => s.id === a.stage_id) &&
          nextSlots.some((s) => s.id === a.slot_id)
            ? a
            : { ...a, stage_id: '', slot_id: '' },
        );
        const assigned = await api.assignSchedule(nextStages, nextSlots, payload);
        const next = {
          ...festival,
          stages: nextStages,
          slots: nextSlots,
          acts: assigned.acts,
        };
        setFestival(next);
        setError(null);
        await refreshSimilarity(assigned.acts);
        const result = await runAnalysis(next, preferences);
        if (result) setAnalysis(result);
      } catch (err) {
        setError({ source: 'structure', message: err.message, code: err.code });
      } finally {
        setStructureBusy(false);
      }
    },
    [acts, festival, preferences, refreshSimilarity, runAnalysis],
  );

  const changePreferences = useCallback(
    async (next) => {
      setPreferences(next);
      setApplied(false);
      const result = await runAnalysis(festival, next);
      if (result) setAnalysis(result);
    },
    [festival, runAnalysis],
  );

  const interpretPlan = useCallback(
    async (instruction) => {
      if (!festival || !festival.acts.length) return;
      const sequence = ++planSeq.current;
      setPlanning(true);
      setPlanError(null);
      try {
        const result = await api.interpretPlan(
          festival.stages,
          festival.slots,
          festival.acts,
          instruction,
        );
        if (sequence !== planSeq.current) return;
        setPlan(result);
      } catch (err) {
        if (sequence !== planSeq.current) return;
        setPlan(null);
        setPlanError(err.message);
      } finally {
        if (sequence === planSeq.current) setPlanning(false);
      }
    },
    [festival],
  );

  // The plan is a set of priorities plus, at most, extra locks the brief asked
  // for. Applying the resulting proposal is still a separate, explicit action.
  const runPlan = useCallback(async () => {
    if (!plan || !festival || planRunning) return;
    const present = new Set(festival.acts.map((act) => act.id));
    const toLock = new Set(
      plan.requested_locks
        .filter((lock) => !lock.already_locked && present.has(lock.act_id))
        .map((lock) => lock.act_id),
    );
    const next = toLock.size
      ? { ...festival, acts: festival.acts.map((act) => (toLock.has(act.id) ? { ...act, fixed: true } : act)) }
      : festival;
    setPlanRunning(true);
    setPlanError(null);
    try {
      if (next !== festival) {
        setFestival(next);
        setLockSources((prev) => {
          const sources = { ...prev };
          for (const actId of toLock) sources[actId] = 'planner';
          return sources;
        });
      }
      // Running a brief always produces a new proposal, so the schedule that was
      // applied earlier no longer matches it and Apply must be live again.
      setApplied(false);
      setPreferences(plan.preferences);
      const result = await runAnalysis(next, plan.preferences);
      if (result) setAnalysis(result);
    } catch (err) {
      setPlanError(err.message);
    } finally {
      setPlanRunning(false);
    }
  }, [festival, plan, planRunning, runAnalysis]);

  // A proposal the user cannot legally run must not reach the schedule.
  const applyOptimized = useCallback(async () => {
    if (!analysis || !analysis.optimized_acts.length || !analysis.valid) return;
    setApplying(true);
    setError(null);
    try {
      const check = await api.validateSchedule(
        festival.stages,
        festival.slots,
        analysis.optimized_acts,
      );
      if (!check.valid) {
        setError({
          source: 'apply',
          message: `The optimizer’s own proposal breaks a rule: ${check.issues.join(' ')}`,
        });
        return;
      }
      const next = { ...festival, acts: analysis.optimized_acts };
      setFestival(next);
      setApplied(true);
      setApplying(false);
      // Re-measure the schedule that now exists, so the panel never compares a
      // stale draft against the proposal the user just accepted.
      const result = await runAnalysis(next, preferences);
      if (result) setAnalysis(result);
    } catch (err) {
      setError({ source: 'apply', message: err.message, code: err.code });
    } finally {
      setApplying(false);
    }
  }, [analysis, festival, preferences, runAnalysis]);

  const profileById = useMemo(() => {
    const map = {};
    for (const profile of similarity?.profiles ?? []) map[profile.entity_id] = profile;
    return map;
  }, [similarity]);

  const stages = festival?.stages ?? [];
  const slots = festival?.slots ?? [];
  // Always the clashes of the schedule that is actually loaded: applying a
  // proposal re-measures from it, so `initial` is the grid the user is looking at
  // and `optimized` would describe a further proposal nobody has accepted.
  const currentClashes = analysis?.initial_clashes;
  const actsById = useMemo(() => Object.fromEntries(acts.map((a) => [a.id, a])), [acts]);

  const clashEntityPairs = useMemo(() => {
    const set = new Set();
    for (const clash of currentClashes ?? []) {
      const ea = actsById[clash.a_id]?.entity_id;
      const eb = actsById[clash.b_id]?.entity_id;
      if (ea && eb) {
        set.add(`${ea}|${eb}`);
        set.add(`${eb}|${ea}`);
      }
    }
    return set;
  }, [currentClashes, actsById]);

  // The intro renders instead of everything below; data loading still runs so
  // the dashboard is ready the moment Get Started is clicked.
  if (route === 'intro') {
    return <AsciiConcertIntro onGetStarted={goDashboard} />;
  }

  if (loading) {
    return (
      <div className="page">
        <div className="loading-screen">
          <div className="spinner" aria-hidden="true" />
          <p>Loading festival data…</p>
        </div>
      </div>
    );
  }

  if (error?.source === 'load') {
    return (
      <div className="page">
        <div className="error-banner" role="alert">
          <strong>Could not load ClashDoctor.</strong>
          <p>{error.message}</p>
          <p>Is the backend running? Start it with the command from the README.</p>
          {error.code && <p className="error-code">{error.code}</p>}
          <button className="btn" onClick={loadDemo}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  const timeRange =
    slots.length > 0 ? `${slots[0].label}–${slots[slots.length - 1].end}` : '';
  const hasMoves = !applied && (analysis?.moves?.length ?? 0) > 0;

  return (
    <div className="page app-enter">
      <header className="masthead">
        <div className="masthead-brand">
          <h1 className="masthead-title">
            Clash<i>Doctor</i>
          </h1>
          <p className="masthead-meta">
            <span className="meta-festival">{festival?.name}</span>
            {timeRange && (
              <>
                <span className="meta-dot">·</span>
                <span>{timeRange}</span>
              </>
            )}
            <span className="meta-dot">·</span>
            <span>
              {acts.length} artist{acts.length === 1 ? '' : 's'} · {stages.length} stages
            </span>
          </p>
        </div>
        <ModeBanner health={health} analysisMode={similarity?.mode} />
      </header>

      <nav className="workflow" aria-label="Workflow">
        <a href="#import">
          <span className="wf-num">01</span> Import
        </a>
        <a href="#schedule">
          <span className="wf-num">02</span> Schedule
        </a>
        <a href="#clashes">
          <span className="wf-num">03</span> Clash report
        </a>
        <a href="#optimize">
          <span className="wf-num">04</span> Optimize
        </a>
        <a href="#similarity">
          <span className="wf-num">05</span> Similarity evidence
        </a>
        <a href="#lineup">
          <span className="wf-num">06</span> Lineup
        </a>
      </nav>

      {error && error.source !== 'load' && (
        <div className="error-banner compact" role="alert">
          <strong>
            {
              {
                structure: 'Schedule update failed:',
                import: 'Import failed:',
                apply: 'Could not apply the proposal:',
              }[error.source] ?? 'Analysis failed:'
            }
          </strong>{' '}
          {error.message}
        </div>
      )}

      {notice && (
        <div className="search-feedback" role="status">
          <span className="stamp stamp-ok">imported</span> {notice}
        </div>
      )}

      <main>
        <section id="import" className="section">
          <SectionTitle
            index="01"
            title="Import a Lineup"
            aside={health?.qloo_configured ? 'csv · pasted text · qloo matching' : 'csv · pasted text'}
          />
          <p className="section-hint">
            Paste or upload a real festival timetable. Parsing and validation run offline in the
            backend; artist names are then resolved through Qloo search, and anything ambiguous is
            put to you for confirmation instead of guessed.
          </p>
          <ImportPanel
            qlooConfigured={Boolean(health?.qloo_configured)}
            busy={importing}
            onImport={importFestival}
          />
        </section>

        <section id="schedule" className="section">
          <SectionTitle
            index="02"
            title="The Schedule"
            aside={`${(currentClashes ?? []).length} clash${(currentClashes ?? []).length === 1 ? '' : 'es'}`}
          />
          {scheduleError && (
            <div className="schedule-error" role="alert">
              <WarningCircle size={15} aria-hidden="true" />
              <span>{scheduleError.message}</span>
              <button
                className="btn btn-small"
                type="button"
                onClick={() => setScheduleError(null)}
              >
                Dismiss
              </button>
            </div>
          )}
          <ScheduleGrid
            stages={stages}
            slots={slots}
            acts={acts}
            clashes={currentClashes}
            proposedActs={hasMoves ? analysis.optimized_acts : null}
            proposedClashes={hasMoves ? analysis.optimized_clashes : null}
            profiles={profileById}
            applied={applied}
            moveCount={analysis?.moves?.length ?? 0}
          />
        </section>

        <div className="analysis-zone">
          <section id="clashes" className="section">
            <SectionTitle
              index="03"
              title="Clash Report"
              aside={applied ? 'applied schedule' : 'draft schedule'}
            />
            <p className="section-hint">
              Artist pairs performing simultaneously on different stages, ordered by estimated
              taste similarity. The percentage is that 0–1 blend rescaled to 100 — it is not a
              share of listeners the two acts actually have in common, and no audience-overlap
              measurement is available from any source. Pairs with missing profiles are excluded
              from scoring and listed honestly; a pair compared on one category or a handful of
              tags is stamped<em> thin evidence</em>.
            </p>
            <ClashSummary
              clashes={currentClashes}
              excluded={analysis?.excluded_pairs}
              fixedClashes={analysis?.fixed_clashes}
              applied={applied}
              actsById={actsById}
              stages={stages}
              slots={slots}
            />
          </section>

          <section id="optimize" className="section">
            <SectionTitle index="04" title="Optimize" aside="priorities you set, numbers we measure" />
            <p className="section-hint">
              The search only proposes schedules that keep every hard constraint: one act per stage
              slot, set lengths that fit, fixed headliners that stay put, and stage or slot
              restrictions respected. What it optimizes is yours to set below; the table reports the
              raw clash sum separately from the prioritized objective, so a weighting choice cannot
              hide a clash.
            </p>
            <PlanningPanel
              plan={plan}
              planning={planning}
              planError={planError}
              analysis={analysis}
              running={planRunning}
              applied={applied}
              acts={acts}
              plannerMode={health?.planner_mode}
              onInterpret={interpretPlan}
              onClear={clearPlan}
              onRun={runPlan}
            />
            <OptimizePanel
              analysis={analysis}
              analyzing={analyzing}
              applying={applying}
              applied={applied}
              preferences={preferences}
              onPreferencesChange={changePreferences}
              onApply={applyOptimized}
              onReset={festival?.mode === 'demo' ? loadDemo : null}
              stages={stages}
              slots={slots}
              actsById={actsById}
            />
          </section>
        </div>

        <section id="similarity" className="section">
          <SectionTitle
            index="05"
            title="Similarity Evidence"
            aside="multi-signal taste blend"
          />
          <p className="section-hint">
            Estimated taste similarity from Qloo tags
            {similarityError
              ? ' — this request failed, so no matrix is shown.'
              : similarity?.mode === 'demo'
                ? ' (demo: deterministic curated dataset with hand-authored profiles, not live Qloo)'
                : similarity?.mode === 'live'
                  ? ' (live: Qloo tag data)'
                  : similarity?.mode === 'unmatched'
                    ? ' (no Qloo profiles — nothing is scored)'
                    : ' (mixed: demo and live profiles)'}
            . Each cell is the weighted blend of the tag categories both artists
            actually have — a category one artist lacks is skipped, never scored as
            disagreement. Outlined cells are scheduled simultaneously in the current
            schedule; starred cells rest on thin evidence. Scores are estimates, not
            verified audience overlap.
          </p>
          {similarityError ? (
            <SimilarityError
              error={similarityError}
              retrying={similarityBusy}
              onRetry={() => refreshSimilarity(acts)}
            />
          ) : (
            <>
              {similarity && similarity.warnings.length > 0 && (
                <div className="warnings-block" role="status">
                  <h3>Partial data warnings</h3>
                  <ul>
                    {similarity.warnings.map((warning, index) => (
                      <li key={index}>
                        <span className="stamp stamp-missing">missing data</span> {warning}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <SimilarityHeatmap acts={acts} similarity={similarity} ringPairs={clashEntityPairs} />
              <PairEvidence similarity={similarity} acts={acts} />
            </>
          )}
        </section>

        <section id="lineup" className="section">
          <SectionTitle
            index="06"
            title="Lineup"
            aside={
              !similarity
                ? acts.length
                  ? 'lineup loaded — similarity unavailable'
                  : 'empty lineup'
                : similarity.mode === 'demo'
                  ? 'seeded demo festival'
                  : similarity.mode === 'live'
                    ? 'live Qloo lineup'
                    : similarity.mode === 'unmatched'
                      ? 'imported, no Qloo profiles'
                      : 'mixed lineup'
            }
          />
          <div className="data-actions">
            <button
              className="btn btn-small"
              type="button"
              onClick={loadDemo}
              disabled={loading}
              title="Load the seeded demo festival — a deterministic curated dataset of fictional artists with hand-authored taste profiles, not live Qloo output (works without an API key)"
            >
              Load demo festival
            </button>
            <button
              className="btn btn-small"
              type="button"
              onClick={startLive}
              disabled={loading || (festival?.mode === 'live' && !acts.length)}
              title="Start a fresh lineup built from live Qloo artist search"
            >
              New lineup
            </button>
            <span className="data-actions-note">
              {festival?.mode === 'demo'
                ? 'Seeded demo dataset — deterministic and curated: fictional artists with hand-authored taste profiles, not live Qloo output.'
                : festival?.mode === 'imported'
                  ? 'Imported lineup — artists carry the Qloo matches you confirmed above.'
                  : 'User-built lineup — artists are added via live Qloo search.'}
            </span>
          </div>
          <p className="section-hint">
            Import a timetable or search Qloo to add artists, then edit stage, slot, or remove acts
            — the analysis re-runs automatically.
          </p>
          <LineupEditor
            acts={acts}
            stages={stages}
            slots={slots}
            profiles={profileById}
            onUpdateAct={updateAct}
            onRemoveAct={removeAct}
            onAddAct={addAct}
            onToggleLock={toggleActLock}
            onClearPlannerLocks={clearPlannerLocks}
            lockSources={lockSources}
            qlooConfigured={health?.qloo_configured}
            structureBusy={structureBusy}
            onAddStage={() =>
              updateStructure(
                [
                  ...stages,
                  { id: `stage-${Date.now()}`, name: `Stage ${stages.length + 1}` },
                ],
                slots,
              )
            }
            onRemoveStage={(stageId) =>
              updateStructure(
                stages.filter((s) => s.id !== stageId),
                slots,
              )
            }
            onAddSlot={(slot) => updateStructure(stages, [...slots, slot])}
            onRemoveSlot={(slotId) =>
              updateStructure(
                stages,
                slots.filter((s) => s.id !== slotId),
              )
            }
          />
        </section>
      </main>

      <footer className="footer">
        ClashDoctor — Qloo tag similarity is a proxy for taste affinity. It is not verified
        audience overlap, shared-fan percentages, or attendance forecasts.
      </footer>
    </div>
  );
}
