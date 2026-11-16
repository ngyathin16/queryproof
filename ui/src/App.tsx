import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, ReactNode } from 'react';
import { z } from 'zod';
import { api, assistanceSchema, display, errorMessage, examplesSchema, jsonObject, metricDisplay, providerSchema, runSchema, snapshotSchema } from './api';
import type { Assistance, Check, Example, JsonObject, Result, ResultTable, Run, Snapshot } from './api';

const draftSchema = z.object({ sql: z.string(), contract: z.string(), snapshot: snapshotSchema, exampleId: z.string(), runId: z.string().nullable() });
const draftKey = 'queryproof-draft-v1';
const passed = 'passed on this snapshot';

function Icon({ name, size = 18 }: { name: 'check' | 'arrow' | 'database' | 'clock' | 'download' | 'play' | 'plus' | 'shield' | 'alert'; size?: number }) {
  const paths: Record<typeof name, ReactNode> = {
    check: <path d="m5 12 4 4L19 6" />,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    database: <><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0" /></>,
    clock: <><circle cx="12" cy="12" r="8" /><path d="M12 7v5l3 2" /></>,
    download: <path d="M12 3v12m-4-4 4 4 4-4M5 15v5h14v-5" />,
    play: <path d="m8 5 11 7-11 7Z" />,
    plus: <path d="M12 5v14M5 12h14" />,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z" /><path d="m8 11 3 3 5-5" /></>,
    alert: <><path d="M12 3 2 20h20ZM12 9v5" /><path d="M12 17h.01" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function tone(status: string) { return status === passed ? 'good' : status === 'issue found' ? 'warning' : 'neutral'; }

function Status({ status }: { status: string }) {
  return <span className={`status ${tone(status)}`}><span aria-hidden="true">{status === passed ? '✓' : status === 'issue found' ? '!' : '·'}</span>{status}</span>;
}

function DataTable({ rows, columns, label }: { rows: ResultTable['rows']; columns?: string[]; label: string }) {
  const first = rows[0];
  const keys = columns ?? (first && !Array.isArray(first) ? Object.keys(first) : Array.isArray(first) ? first.map((_, i) => String(i + 1)) : []);
  if (!rows.length) return <p className="muted small">No rows to display.</p>;
  return <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>
    <table><caption className="sr-only">{label}</caption><thead><tr>{keys.map(key => <th key={key} scope="col">{key.replaceAll('_', ' ')}</th>)}</tr></thead>
      <tbody>{rows.slice(0, 20).map((row, index) => <tr key={index}>{keys.map((key, columnIndex) => { const value = Array.isArray(row) ? row[columnIndex] : row[key]; return <td key={key}>{value === null ? 'NULL' : value === undefined ? 'Absent' : display(value)}</td>; })}</tr>)}</tbody>
    </table>
  </div>;
}

function Finding({ check, index }: { check: Check; index: number }) {
  return <details className={`finding ${tone(check.status)}`} open={check.status === 'issue found' && index === 0}>
    <summary><span className="finding-symbol" aria-hidden="true">{check.status === passed ? '✓' : check.status === 'issue found' ? '!' : '?'}</span><span className="finding-heading"><strong>{check.title}</strong><span className="muted small">{check.status}</span></span><span className="detail-toggle" aria-hidden="true">+</span></summary>
    <div className="finding-content"><p>{check.explanation}</p>
      <dl className="evidence-meta"><div><dt>Contract clause</dt><dd>{display(check.contract_clause)}</dd></div><div><dt>SQL location</dt><dd>{display(check.sql_location)}</dd></div></dl>
      {check.diagnostic_sql && <><h4>Reproduce this finding</h4><pre tabIndex={0} aria-label={`${check.title} diagnostic SQL`}><code>{check.diagnostic_sql}</code></pre></>}
      {check.count !== undefined && check.count !== null && <p className="small"><strong>{display(check.count)} affected {check.count === 1 ? 'row' : 'rows'}</strong>{check.examples.length > 0 ? ` · ${check.examples.length} shown` : ''}{check.truncated ? ' · Examples truncated to 20 rows.' : ''}</p>}
      {check.examples.length > 0 && <DataTable rows={check.examples} label={`${check.title} example rows`} />}
    </div>
  </details>;
}

function ContractSummary({ contract }: { contract: JsonObject | null }) {
  if (!contract) return <p className="small muted">Enter valid JSON to preview the definition.</p>;
  const measure = jsonObject.safeParse(contract.measure);
  const time = jsonObject.safeParse(contract.time);
  return <dl className="contract-summary">
    <div><dt>Metric</dt><dd>{display(contract.name)}</dd></div>
    <div><dt>Grain</dt><dd>{display(contract.grain)}</dd></div>
    <div><dt>Measure</dt><dd>{measure.success ? `${display(measure.data.aggregation).toUpperCase()}(${display(measure.data.column)})` : 'Needs definition'}</dd></div>
    <div><dt>Population</dt><dd>{Array.isArray(contract.filters) && contract.filters.length ? contract.filters.map((filter, index) => {
      const parsed = jsonObject.safeParse(filter);
      return <span className="contract-filter" key={index}>{parsed.success ? `${display(parsed.data.column)} ${display(parsed.data.op)} ${display(parsed.data.value)}` : display(filter)}</span>;
    }) : Array.isArray(contract.filters) ? 'All rows (explicit)' : 'Needs definition'}</dd></div>
    <div><dt>Window</dt><dd>{time.success ? <>{display(time.data.start)}<br /><span className="muted">to </span>{display(time.data.end)} <span className="muted">(exclusive)</span><br /><span className="small muted">{display(time.data.timezone)}</span></> : 'Needs definition'}</dd></div>
    <div><dt>Nulls / units</dt><dd>{display(contract.null_policy)} / {display(contract.units)}</dd></div>
  </dl>;
}

function ReviewResult({ result, units }: { result: Result; units: string }) {
  const original = Number(result.original?.total);
  const reference = Number(result.reference?.total);
  const numeric = result.original?.total !== null && result.original?.total !== undefined && result.reference?.total !== null && result.reference?.total !== undefined && Number.isFinite(original) && Number.isFinite(reference);
  const absolute = result.difference?.absolute;
  const difference = typeof absolute === 'number' || typeof absolute === 'string' ? absolute : null;
  const isZero = difference !== null && /^[+-]?0+(?:\.0+)?(?:[eE][+-]?\d+)?$/.test(String(difference));
  const positive = difference !== null && !isZero && !String(difference).startsWith('-');
  const rawPercent = result.difference?.percent;
  const percent = typeof rawPercent === 'number' && Number.isFinite(rawPercent) ? Math.abs(rawPercent) : null;
  const percentText = percent === null ? 'Compared on this snapshot' : `${percent > 0 && percent < 0.1 ? '<0.1' : percent.toFixed(1)}% ${isZero ? 'difference' : positive ? 'above reference' : 'below reference'}`;
  const chartable = numeric && Math.abs(original) <= Number.MAX_SAFE_INTEGER && Math.abs(reference) <= Number.MAX_SAFE_INTEGER;
  const max = numeric ? Math.max(Math.abs(original), Math.abs(reference), 1) : 1;
  const queryTotal = metricDisplay(result.original?.total);
  const referenceTotal = metricDisplay(result.reference?.total);
  return <section className="panel result-panel" aria-labelledby="findings-title">
    <div className="panel-header"><div><p className="eyebrow">02 / The evidence</p><h2 id="findings-title">{result.status === passed ? 'The results agree.' : result.status === 'issue found' ? 'This number needs a closer look.' : 'More evidence is needed.'}</h2></div><Status status={result.status} /></div>
    {(result.original || result.reference) && <><div className="metric-grid">
      <div><span className="metric-label">Your query</span><strong>{queryTotal}</strong><span className="metric-unit">{units} · reported</span></div>
      <div><span className="metric-label">Independent reference</span><strong className="reference-number">{referenceTotal}</strong><span className="metric-unit">{units} · from your definition</span></div>
      <div className={difference !== null && !isZero ? 'difference-warning' : ''}><span className="metric-label">Difference</span><strong>{`${positive ? '+' : ''}${metricDisplay(difference)}`}</strong><span className="metric-unit">{percentText}</span></div>
    </div>{chartable && <div className="comparison-bars" aria-label="Query and reference totals"><div><span>Query</span><div className="bar-track"><span className="bar query-bar" style={{ width: `${Math.abs(original) / max * 100}%` }} /></div><span>{queryTotal}</span></div><div><span>Reference</span><div className="bar-track"><span className="bar reference-bar" style={{ width: `${Math.abs(reference) / max * 100}%` }} /></div><span>{referenceTotal}</span></div></div>}</>}
    {(result.original?.total === null || result.reference?.total === null) && <p className="total-note small muted">No additive headline total is available. Inspect the complete grouped results below; averages, ratios, and distinct counts must be compared per group.</p>}
    <div className="checks-header"><h3>Checks against your definition</h3><span className="muted small">{result.checks.length} checks</span></div>
    <div className="findings">{result.checks.map((check, index) => <Finding check={check} index={index} key={check.id} />)}</div>
    {(result.original || result.reference) && <details className="result-detail"><summary>Compare grouped results</summary><p className="small muted">All groups are compared by the engine. Tables display up to 20 rows; NULL, zero, and an absent group are distinct.</p><div className="group-tables">{result.original && <div><h4>Your query</h4><DataTable {...result.original} label="Original query groups" /></div>}{result.reference && <div><h4>Independent reference</h4><DataTable {...result.reference} label="Reference groups" /></div>}</div></details>}
    {result.difference?.population && <details className="result-detail"><summary>Inspect the intended population</summary><pre tabIndex={0}>{JSON.stringify(result.difference.population, null, 2)}</pre></details>}
    {result.limitations.length > 0 && <div className="limits"><Icon name="shield" /><div><strong>What this review can establish</strong>{result.limitations.map((limit, i) => <p key={i}>{limit}</p>)}</div></div>}
  </section>;
}

export function App() {
  const [examples, setExamples] = useState<Example[]>([]);
  const [exampleId, setExampleId] = useState('');
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [sql, setSql] = useState('');
  const [contractText, setContractText] = useState('');
  const [run, setRun] = useState<Run | null>(null);
  const [history, setHistory] = useState<Run[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('Loading your workbench…');
  const [candidate, setCandidate] = useState('');
  const [candidateRun, setCandidateRun] = useState<Run | null>(null);
  const [candidateSource, setCandidateSource] = useState('Deterministic suggestion');
  const [includeExamples, setIncludeExamples] = useState(false);
  const [provider, setProvider] = useState<z.infer<typeof providerSchema> | null>(null);
  const [assistance, setAssistance] = useState<Assistance | null>(null);
  const [assisting, setAssisting] = useState(false);
  const [consent, setConsent] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);
  const generation = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const candidateField = useRef<HTMLTextAreaElement>(null);
  let contract: JsonObject | null = null;
  let contractError = '';
  try { contract = jsonObject.parse(JSON.parse(contractText)); } catch { contractError = 'The metric definition must be a valid JSON object.'; }
  const fingerprint = JSON.stringify([snapshot?.id, sql, contract]);
  const current = run !== null && fingerprint === JSON.stringify([run.snapshot_id, run.sql, run.contract]);
  const candidateCurrent = candidateRun !== null && JSON.stringify([snapshot?.id, candidate, contract]) === JSON.stringify([candidateRun.snapshot_id, candidateRun.sql, candidateRun.contract]);
  const activeRun = candidateRun?.status === 'running' ? candidateRun : run?.status === 'running' ? run : null;
  const working = busy || activeRun !== null;
  const acceptedCandidate = candidateCurrent && candidateRun?.status === 'completed' && candidateRun.result?.status === passed && current;
  const selectedExample = examples.find(example => example.id === exampleId);
  const units = contract ? display(contract.units) : '';

  async function loadExample(example: Example) {
    const version = ++generation.current;
    setBusy(true); setError(''); setNotice('Loading the bundled snapshot…');
    try {
      const loaded = await api('/snapshots', snapshotSchema, { bundle: example.bundle });
      if (version !== generation.current) return;
      setSnapshot(loaded); setExampleId(example.id); setSql(example.sql); setContractText(JSON.stringify(example.contract, null, 2));
      setRun(null); setCandidate(''); setCandidateRun(null); setAssistance(null); setConsent(false); setIncludeExamples(false);
      setNotice('Snapshot loaded. Confirm the definition, then run your review.');
    } catch (error) { setError(errorMessage(error)); }
    finally { if (version === generation.current) setBusy(false); }
  }

  useEffect(() => {
    let mounted = true;
    async function start() {
      try {
        const [loadedExamples, loadedHistory, loadedProvider] = await Promise.all([
          api('/examples', examplesSchema), api('/runs', z.array(runSchema)), api('/provider', providerSchema).catch(() => null),
        ]);
        if (!mounted) return;
        setExamples(loadedExamples); setHistory(loadedHistory); setProvider(loadedProvider);
        let saved: z.infer<typeof draftSchema> | null = null;
        try { saved = draftSchema.parse(JSON.parse(localStorage.getItem(draftKey) ?? 'null')); } catch { /* An absent or older draft starts with the bundled example. */ }
        if (saved) {
          const loadedSnapshot = await api(`/snapshots/${encodeURIComponent(saved.snapshot.id)}`, snapshotSchema).catch(() => null);
          if (loadedSnapshot && mounted) {
            setSnapshot(loadedSnapshot); setSql(saved.sql); setContractText(saved.contract); setExampleId(saved.exampleId);
            if (saved.runId) setRun(await api(`/runs/${encodeURIComponent(saved.runId)}`, runSchema));
            setNotice('Your local draft has been restored.'); setBusy(false);
          } else if (loadedExamples[0]) await loadExample(loadedExamples[0]);
        } else if (loadedExamples[0]) await loadExample(loadedExamples[0]);
        else { setBusy(false); setNotice('Import a dataset to begin.'); }
      } catch (error) { if (mounted) { setError(errorMessage(error)); setBusy(false); setNotice('Could not load the workbench.'); } }
      finally { if (mounted) setSessionReady(true); }
    }
    void start();
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (!sessionReady || !snapshot) return;
    try { localStorage.setItem(draftKey, JSON.stringify({ sql, contract: contractText, snapshot, exampleId, runId: run?.id ?? null })); } catch { /* Server history still preserves every completed review. */ }
  }, [sql, contractText, snapshot, exampleId, run?.id, sessionReady]);

  useEffect(() => {
    if (!activeRun) return;
    let stopped = false;
    let timeout: ReturnType<typeof setTimeout>;
    const id = activeRun.id;
    const isCandidate = candidateRun?.id === id;
    async function poll() {
      try {
        const next = await api(`/runs/${encodeURIComponent(id)}`, runSchema);
        if (stopped) return;
        if (isCandidate) setCandidateRun(next); else setRun(next);
        if (next.status === 'running') timeout = setTimeout(() => void poll(), 350);
        else {
          setNotice(next.status === 'completed' ? `Review finished: ${next.result?.status ?? 'see findings'}.` : `Review ${next.status}.`);
          if (next.error) setError(next.error);
          setHistory(await api('/runs', z.array(runSchema)));
        }
      } catch (error) { if (!stopped) { setError(errorMessage(error)); timeout = setTimeout(() => void poll(), 1500); } }
    }
    timeout = setTimeout(() => void poll(), 100);
    return () => { stopped = true; clearTimeout(timeout); };
  }, [activeRun?.id]);

  async function startReview(isCandidate = false) {
    if (!snapshot || !contract) { setError(contractError || 'Load a dataset first.'); return; }
    setBusy(true); setError(''); setNotice(isCandidate ? 'Checking the proposed revision…' : 'Running the independent review…');
    try {
      const created = await api('/runs', z.object({ id: z.string(), status: z.string() }), {
        snapshot_id: snapshot.id, contract, sql: isCandidate ? candidate : sql, ...(isCandidate && run ? { parent_id: run.id } : {}),
      });
      const loaded = await api(`/runs/${encodeURIComponent(created.id)}`, runSchema);
      if (isCandidate) setCandidateRun(loaded); else { setRun(loaded); setCandidateRun(null); setCandidate(''); setAssistance(null); }
      if (loaded.status !== 'running') { setNotice(`Review ${loaded.status}: ${loaded.result?.status ?? loaded.error ?? 'see findings'}.`); setHistory(await api('/runs', z.array(runSchema))); }
    } catch (error) { setError(errorMessage(error)); setNotice('Review could not start.'); }
    finally { setBusy(false); }
  }

  async function cancelReview() {
    if (!activeRun) return;
    try { await api(`/runs/${encodeURIComponent(activeRun.id)}/cancel`, z.unknown(), {}); setNotice('Cancellation requested. Waiting for the worker to stop.'); }
    catch (error) { setError(errorMessage(error)); }
  }

  async function openRun(id: string) {
    setBusy(true); setError('');
    try {
      const selected = await api(`/runs/${encodeURIComponent(id)}`, runSchema);
      const loaded = await api(`/snapshots/${encodeURIComponent(selected.snapshot_id)}`, snapshotSchema);
      setRun(selected); setSnapshot(loaded); setSql(selected.sql); setContractText(JSON.stringify(selected.contract, null, 2));
      setCandidate(''); setCandidateRun(null); setAssistance(null); setConsent(false); setHistoryOpen(false); setExampleId('');
      setNotice('Saved evidence opened. Edits create a new review.');
    } catch (error) { setError(errorMessage(error)); }
    finally { setBusy(false); }
  }

  async function importFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    setBusy(true); setError('');
    try {
      if (files.reduce((total, file) => total + file.size, 0) > 100 * 1024 * 1024) throw new Error('Select at most 100 MB of input.');
      const manifestFile = files.find(file => file.name.endsWith('.json'));
      if (!manifestFile) throw new Error('Select a JSON manifest along with its CSV files, or one JSON bundle.');
      const parsed = jsonObject.parse(JSON.parse(await manifestFile.text()));
      let bundle: JsonObject;
      if ('manifest' in parsed && 'files' in parsed) bundle = parsed;
      else {
        const contents: Record<string, string> = {};
        for (const file of files.filter(file => file !== manifestFile)) contents[file.name] = await file.text();
        bundle = { manifest: parsed, files: contents };
      }
      const loaded = await api('/snapshots', snapshotSchema, { bundle });
      setSnapshot(loaded); setExampleId(''); setRun(null); setCandidate(''); setCandidateRun(null); setAssistance(null); setConsent(false); setImportOpen(false);
      setSql(''); setContractText('{}'); setNotice('Local data imported. Define the metric and enter your SQL.');
    } catch (error) { setError(errorMessage(error)); }
    finally { setBusy(false); if (fileInput.current) fileInput.current.value = ''; }
  }

  function propose(sql: string, source: string) {
    setCandidate(sql); setCandidateSource(source); setCandidateRun(null);
    setNotice('Proposal ready. Review the SQL and run the checks before accepting.');
    setTimeout(() => candidateField.current?.focus(), 0);
  }

  async function assist() {
    if (!run || !consent) return;
    setAssisting(true); setError(''); setAssistance(null);
    try {
      const result = await api(`/runs/${encodeURIComponent(run.id)}/assist`, assistanceSchema, { consent: true });
      setAssistance(result); setNotice(`Live assistance ${result.status}. Deterministic evidence is unchanged.`);
    } catch (error) { setAssistance({ status: 'failed', error: errorMessage(error) }); }
    finally { setAssisting(false); }
  }

  const modelProposal = typeof assistance?.proposal === 'string' ? assistance.proposal : assistance?.proposal?.sql ?? assistance?.sql;
  const assistanceTime = assistance?.elapsed_seconds ?? (assistance?.elapsed_ms !== undefined ? assistance.elapsed_ms / 1000 : undefined);
  const assistanceUsage = assistance?.usage ?? assistance?.tokens;
  const assistanceActivity = assistance?.tool_activity ?? assistance?.activity ?? assistance?.tools;
  let providerHost = 'Not configured';
  try { if (provider?.endpoint) providerHost = new URL(provider.endpoint).hostname; } catch { providerHost = 'Invalid endpoint configuration'; }
  return <>
    <a className="skip-link" href="#main">Skip to workbench</a>
    <header className="topbar"><a className="brand" href="/" aria-label="QueryProof home"><span className="brand-mark"><Icon name="check" size={23} /></span>Query<span>Proof</span><span className="beta">LOCAL PREVIEW</span></a><nav aria-label="Workbench navigation"><button className={!historyOpen ? 'nav-link active' : 'nav-link'} aria-pressed={!historyOpen} onClick={() => setHistoryOpen(false)}>Workbench</button><button className={historyOpen ? 'nav-link active' : 'nav-link'} aria-pressed={historyOpen} onClick={() => setHistoryOpen(!historyOpen)}><Icon name="clock" size={16} />History{history.length > 0 && <span className="history-count">{history.length}</span>}</button></nav><span className="local-label"><span className="dot" /> Runs on your machine</span></header>
    <main id="main" tabIndex={-1} className="shell">
      <div className="page-heading"><div><p className="eyebrow">SQL REVIEW WORKBENCH</p><h1>Evidence before <em>confidence.</em></h1><p className="page-intro">A query can run perfectly and still tell the wrong story. Check the definition. Follow the rows.</p></div><div className="mode-label"><Icon name="shield" /><div><strong>Deterministic review</strong><span>No model or API key required</span></div></div></div>
      <div className="announcement" role="status" aria-live="polite"><span className={working ? 'dot busy-dot' : 'dot'} /><span>{notice}</span></div>
      {error && <div className="error-banner" role="alert"><Icon name="alert" /><div><strong>We couldn’t complete that action.</strong><p>{error}</p></div><button className="text-button" onClick={() => setError('')} aria-label="Dismiss error">Dismiss</button></div>}
      {historyOpen && <section className="panel history-panel" aria-labelledby="history-title"><div className="panel-header"><div><p className="eyebrow">Saved on this machine</p><h2 id="history-title">Every review keeps its evidence.</h2></div><button className="text-button" onClick={() => setHistoryOpen(false)}>Close history</button></div>{history.length ? <div className="history-list">{history.map(item => <button disabled={working || assisting} className="history-item" key={item.id} onClick={() => void openRun(item.id)}><Icon name="clock" /><span><strong>{display(item.contract.name)}</strong><span>{new Date(item.created_at).toLocaleString()} · {item.id.slice(0, 8)}{item.parent_id ? ' · revision' : ''}</span></span><Status status={item.result?.status ?? item.status} /><Icon name="arrow" /></button>)}</div> : <p className="muted">Run your first review. Its snapshot, SQL, definition, and evidence will be saved here.</p>}</section>}
      <div className="workbench">
        <aside className="sidebar" aria-label="Analysis context">
          <section className="panel dataset-panel"><div className="sidebar-heading"><Icon name="database" /><h2>Your dataset</h2></div><label className="field-label" htmlFor="example">Start with an example</label><select id="example" value={exampleId} disabled={working || assisting} onChange={event => { const example = examples.find(item => item.id === event.target.value); if (example) void loadExample(example); }}><option value="" disabled>Local dataset</option>{examples.map(example => <option key={example.id} value={example.id}>{example.title}</option>)}</select>
            <p className="small muted example-description">{selectedExample?.description ?? 'An immutable snapshot of your locally imported tables.'}</p>
            {snapshot && <><div className="snapshot-name"><span className="dot" /><strong>{snapshot.name ?? 'Local snapshot'}</strong></div><div className="schema-list">{Object.entries(snapshot.tables).map(([name, table]) => <details className="schema-table" key={name}><summary><span><Icon name="database" size={14} />{name}</span><span className="row-count">{table.row_count.toLocaleString()} rows</span></summary><dl>{table.columns.map(column => <div key={column.name}><dt>{column.name}</dt><dd>{column.type}</dd></div>)}</dl></details>)}</div><div className="snapshot-id"><span>SNAPSHOT</span><code title={snapshot.id}>{snapshot.id.slice(0, 16)}</code></div></>}
            <button className="button secondary full-width import-button" aria-expanded={importOpen} onClick={() => setImportOpen(!importOpen)} disabled={working || assisting}><Icon name="plus" size={16} />Import your data</button>
            {importOpen && <div className="import-panel"><p className="small">Choose a JSON bundle, or select a JSON manifest and its CSV files together. Up to 5 tables, 100 MB, and 1 million rows.</p><label className="field-label" htmlFor="files">Manifest and data files</label><input ref={fileInput} id="files" type="file" multiple accept=".json,.csv" onChange={event => void importFiles(event)} /><details><summary className="small">Manifest format</summary><pre tabIndex={0}>{'{\n  "name": "My data",\n  "tables": [{\n    "name": "orders",\n    "file": "orders.csv",\n    "columns": [{\n      "name": "order_id",\n      "type": "INTEGER"\n    }]\n  }]\n}'}</pre></details></div>}
          </section>
          <section className="panel contract-panel"><div className="sidebar-heading"><span className="contract-icon">≡</span><h2>The metric definition</h2></div><p className="small muted">What should this number mean? The review checks your SQL against this contract.</p><ContractSummary contract={contract} /><details className="contract-editor"><summary>Edit the definition <span aria-hidden="true">↗</span></summary><label className="field-label" htmlFor="contract">Metric contract · JSON</label><textarea id="contract" value={contractText} spellCheck={false} onChange={event => setContractText(event.target.value)} rows={18} aria-invalid={Boolean(contractError && contractText)} aria-describedby="contract-help" /><p id="contract-help" className="small muted">Edits invalidate current results. An incomplete definition will be reported as needing definition.</p>{contractError && <p className="small validation-error">{contractError}</p>}</details></section>
          <div className="privacy-note"><Icon name="shield" size={17} /><p>Reviews run locally. Only evidence you explicitly select for live assistance goes to your configured provider.</p></div>
        </aside>
        <div className="review-column">
          <section className="panel sql-panel" aria-labelledby="sql-title"><div className="panel-header"><div><p className="eyebrow">01 / The question</p><h2 id="sql-title">{contract?.name ? display(contract.name) : 'Define your analysis'}</h2></div><span className="sql-dialect">DuckDB SQL</span></div><div className="editor-heading"><label htmlFor="sql">SQL to review</label><span>Read-only · bounded grammar</span></div><div className="code-editor"><div className="line-numbers" aria-hidden="true">{sql.split('\n').map((_, index) => <span key={index}>{index + 1}</span>)}</div><textarea id="sql" value={sql} onChange={event => setSql(event.target.value)} spellCheck={false} rows={Math.min(Math.max(sql.split('\n').length, 7), 16)} placeholder="SELECT …" aria-describedby="sql-help" /></div><div className="editor-actions"><p id="sql-help"><Icon name="shield" size={15} /> Checked against an independent calculation.</p><div className="button-row"><button className="text-button" disabled={working || assisting || !examples[0]} onClick={() => { if (examples[0]) void loadExample(examples[0]); }}>Reset example</button>{activeRun ? <button className="button secondary" onClick={() => void cancelReview()}>Cancel review</button> : <button className="button primary" disabled={busy || assisting || !snapshot || !sql.trim() || !contract} onClick={() => void startReview()}><Icon name="play" size={15} />Run review</button>}</div></div><details className="grammar"><summary>What SQL can I review?</summary><p>One SELECT, up to two aggregate CTEs, and two INNER or LEFT equijoins. SUM, COUNT, COUNT DISTINCT, AVG, arithmetic, numeric casts, COALESCE, NULLIF, grouping, ordering, and explicit literal filters are supported. Windows, HAVING, subqueries, set operations, general DISTINCT, LIMIT, table functions, and writes are rejected.</p></details></section>
          {run && !current && <div className="stale-banner" role="status"><Icon name="alert" /><div><strong>Inputs changed — these are earlier results.</strong><p>Run the review again to check the current SQL, definition, and snapshot.</p></div></div>}
          {activeRun && <div className="panel progress-panel" aria-label="Review in progress"><span className="spinner" /><div><strong>Following the rows…</strong><p>Executing the query, checking the population, and calculating an independent reference.</p></div></div>}
          {run?.status === 'interrupted' && <div className="stale-banner"><Icon name="alert" /><div><strong>This review was interrupted.</strong><p>No completed result is claimed. Run it again to collect new evidence.</p></div></div>}
          {run?.status === 'failed' && <div className="error-banner"><Icon name="alert" /><div><strong>The review failed.</strong><p>{run.error ?? 'The query could not be evaluated. Correct it and run again.'}</p></div></div>}
          {run?.result && <ReviewResult result={run.result} units={display(run.contract.units)} />}
          {!run && !activeRun && <section className="empty-state" aria-labelledby="empty-title"><div className="empty-illustration" aria-hidden="true"><div className="mini-row"><span /><span /><b /></div><div className="mini-row"><span /><span /><b /></div><div className="mini-row"><span /><span /><b /></div><span className="evidence-seal"><Icon name="check" size={22} /></span></div><h2 id="empty-title">Let’s see what the rows say.</h2><p>Run a review to compare your result with the metric definition.<br />Every finding comes with evidence you can inspect.</p><div className="workflow"><span>01 <b>Check the query</b></span><i aria-hidden="true">→</i><span>02 <b>Inspect the evidence</b></span><i aria-hidden="true">→</i><span>03 <b>Verify a revision</b></span></div></section>}
          {run?.result && current && <>
            <section className="panel revision-panel" aria-labelledby="revision-title"><div className="panel-header"><div><p className="eyebrow">03 / A considered revision</p><h2 id="revision-title">Change the query. Keep the meaning.</h2></div></div>{run.result.proposal && !candidate && <div className="proposal-intro"><p>{run.result.proposal.explanation}</p><button className="button secondary" onClick={() => { if (run.result?.proposal) propose(run.result.proposal.sql, 'Deterministic suggestion'); }} disabled={working || assisting}>Inspect suggested repair <Icon name="arrow" size={15} /></button><span className="small muted">Deterministic suggestion · not yet accepted</span></div>}
              {!run.result.proposal && !candidate && <p className="muted">{run.result.status === passed ? 'This query agrees with the current contract on this snapshot. You can export the evidence below.' : 'There is no deterministic repair for this review. You can edit the SQL above or request an optional live-model proposal.'}</p>}
              {candidate && <><span className="mode-chip">{candidateSource}</span><div className="revision-compare"><div><h3>Original SQL</h3><pre tabIndex={0} aria-label="Original SQL"><code>{run.sql}</code></pre></div><div><label className="field-label" htmlFor="candidate">Proposed SQL</label><textarea ref={candidateField} id="candidate" value={candidate} spellCheck={false} rows={12} onChange={event => setCandidate(event.target.value)} /></div></div><div className="revision-actions"><p className="small muted">Your original review and contract are preserved. A proposal must pass before you can accept it.</p><button className="button secondary" disabled={working || assisting || !candidate.trim()} onClick={() => void startReview(true)}>Check revision <Icon name="arrow" size={15} /></button></div>{candidateRun && <div className="candidate-summary"><h3>Revision check</h3>{!candidateCurrent && <p className="validation-error">Proposal changed. Run its checks again before accepting.</p>}<Status status={candidateRun.result?.status ?? candidateRun.status} />{candidateRun.result?.original && <p>Revised total: <strong>{metricDisplay(candidateRun.result.original.total)} {units}</strong>. Original total: <strong>{metricDisplay(run.result.original?.total)} {units}</strong>.</p>}{candidateRun.error && <p className="validation-error">{candidateRun.error}</p>}{candidateRun.result?.difference?.population && <details><summary>Population comparison</summary><pre tabIndex={0}>{JSON.stringify(candidateRun.result.difference.population, null, 2)}</pre></details>}{candidateRun.result?.checks.map((check, index) => <Finding check={check} index={index} key={check.id} />)}{candidateRun.result?.limitations.length ? <div className="small muted"><strong>Remaining limitations</strong>{candidateRun.result.limitations.map((limit, index) => <p key={index}>{limit}</p>)}</div> : null}<button className="button primary" disabled={!acceptedCandidate || working || assisting} onClick={() => { if (candidateRun && acceptedCandidate) { setSql(candidate); setRun(candidateRun); setCandidate(''); setCandidateRun(null); setAssistance(null); setNotice('Revision accepted. The original review remains in history.'); } }}><Icon name="check" size={16} />Accept checked revision</button></div>}</>}
              <details className="assistant-panel"><summary><span className="ai-spark" aria-hidden="true">✧</span>Optional live assistance <span className="small muted">{provider?.model ?? 'Configure a provider'}</span></summary><p className="small">Ask a model to inspect the completed findings and propose SQL. It cannot edit your metric definition. Any proposal goes through the same checks.</p><details className="provider-setup"><summary>Configure a different model or provider</summary><p>Configure the provider and model in the server environment, then restart QueryProof. API keys belong in the server environment and are never entered or stored in this browser. Hosted inference may incur charges from your provider.</p><pre tabIndex={0} aria-label="Hosted provider environment settings">{'QUERYPROOF_PROVIDER=openai-compatible\nQUERYPROOF_API_BASE=https://api.openai.com/v1\nQUERYPROOF_MODEL=your-model-id\nQUERYPROOF_API_KEY=your-server-only-key'}</pre><p>For a local model, use QUERYPROOF_PROVIDER=ollama and QUERYPROOF_MODEL with your installed model name. No API key is needed.</p></details><div className="provider-meta"><span>{provider?.local ? "Local provider" : "Remote provider"}: <strong>{provider?.provider ?? "Not configured"}</strong> / {providerHost}</span><span>Model: <strong>{provider?.model ?? "Not configured"}</strong></span><span>Limit: 8 tool calls / 60 seconds</span></div><label className="checkbox-label"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} disabled={assisting} /><span>I choose to send this review’s SQL, metric definition, schema, and bounded finding evidence to the configured provider.</span></label><button className="button secondary" disabled={!consent || assisting || working || !provider?.model || provider?.configured === false} onClick={() => void assist()}>{assisting ? 'Model is working…' : 'Request live assistance'}<Icon name="arrow" size={15} /></button>{assistance && <div className="assistance-result"><Status status={`Live assistance: ${assistance.status}`} />{assistance.error && <p className="validation-error">{assistance.error}</p>}{(assistance.explanation || (typeof assistance.proposal === "object" && assistance.proposal?.explanation)) && <p>{assistance.explanation ?? (typeof assistance.proposal === "object" ? assistance.proposal?.explanation : "")}</p>}<p className="small muted">{assistance.model ?? provider?.model}{assistanceTime !== undefined ? ` · ${assistanceTime.toFixed(1)} seconds` : ''}</p>{assistanceUsage && <p className="small">Reported token usage: {display(assistanceUsage)}</p>}{assistanceActivity && <details><summary>Tool activity</summary><pre tabIndex={0}>{JSON.stringify(assistanceActivity, null, 2)}</pre></details>}{modelProposal && <button className="button secondary" onClick={() => propose(modelProposal, `Live model proposal · ${assistance.model ?? provider?.model ?? 'configured model'}`)}>Inspect model proposal</button>}</div>}</details>
            </section>
            <section className="panel export-panel" aria-labelledby="export-title"><div><p className="eyebrow">Keep the evidence</p><h2 id="export-title">A review someone else can reproduce.</h2><p className="small muted">SQL, contract, snapshot identity, checks, and reproduction instructions. Raw input rows are excluded.</p><label className="checkbox-label small"><input type="checkbox" checked={includeExamples} onChange={event => setIncludeExamples(event.target.checked)} />Include the labeled example rows from findings</label></div><div className="export-buttons"><a className="button primary" href={`/api/runs/${encodeURIComponent(run.id)}/export?format=html&examples=${includeExamples ? '1' : '0'}`} download><Icon name="download" size={16} />HTML report</a><a className="button secondary" href={`/api/runs/${encodeURIComponent(run.id)}/export?format=json&examples=${includeExamples ? '1' : '0'}`} download><Icon name="download" size={16} />JSON evidence</a></div></section>
          </>}
        </div>
      </div>
      <footer className="footer"><span className="footer-brand">QueryProof <span> / </span> Evidence before confidence.</span><span>Local preview · Results are conditional on your contract and snapshot.</span></footer>
    </main>
  </>;
}
