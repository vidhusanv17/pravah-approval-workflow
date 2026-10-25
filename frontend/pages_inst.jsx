/* Institution portal + public verification page. */

function InstitutionHome({ user, go, refreshKey }) {
  const { data, error } = useApi("/institutions/" + user.institution_id, [refreshKey]);
  const dash = useApi("/dashboard/summary", [refreshKey]);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;
  const i = data;
  const k = dash.data && dash.data.kpis;
  return (<div className="fade">
    <Section title={i.name} right={<div className="text-[12px] text-slate-500">{i.pid} · {i.region_label}</div>} />
    {k && <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      <KPI label="My applications in process" value={k.pending} tone="blue" onClick={() => go("my-applications")} />
      <KPI label="Returned - action needed" value={k.returned} tone="amber" onClick={() => go("my-applications")} />
      <KPI label="Undertakings due in 30 d / overdue" value={k.undertakings_due_30 + " / " + k.undertakings_overdue} tone={k.undertakings_overdue ? "red" : "green"} onClick={() => go("undertakings")} />
      <KPI label="Documents expiring / expired" value={k.docs_expiring_90 + " / " + k.docs_expired} tone={k.docs_expired ? "red" : "amber"} onClick={() => go("documents")} />
    </div>}
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
      <div><ReadinessCard r={i.readiness} /><div className="mt-3"><Btn tone="primary" onClick={() => go("submit")}>Submit a new application</Btn></div>
        <div className="mt-3 rounded-lg border border-slate-200 p-3 text-[12px]"><div className="text-slate-500">Compliance score</div><div className="text-3xl font-bold">{i.compliance_score} <Chip value={i.compliance_band} label={i.compliance_band === "GREEN" ? "Green Channel" : i.compliance_band} /></div>{i.score_breakdown.map((b, x) => <div key={x} className="flex justify-between"><span>{b.factor}</span><b className="text-red-700">{b.delta}</b></div>)}</div></div>
      <div className="lg:col-span-2 space-y-3">
        <Card title="Application tracker" right={<a href="#/my-applications" className="text-[11px] text-blue-700">all</a>}>{i.applications.slice(0, 4).map(a => <TrackerRow key={a.id} a={a} go={go} />)}{i.applications.length === 0 && <Empty text="No applications yet" />}</Card>
        <Card title="Recent alerts & reminders for your institution">{i.alerts.length === 0 && <Empty text="No alerts" />}<ul className="divide-y divide-slate-100">{i.alerts.slice(0, 6).map(a => <li key={a.id} className="py-2 text-[12px]"><Chip value={a.severity} /> <span className="ml-1">{a.title}</span><div className="text-[11px] text-slate-400">{a.message}</div></li>)}</ul></Card>
      </div></div></div>);
}
function TrackerRow({ a, go }) {
  const steps = ["Submitted", "Scrutiny", "EVC", "SAC/SHC", "Approval"];
  return (<div className="py-2 border-b border-slate-100 text-[12px] cursor-pointer hover:bg-slate-50 rounded px-1" onClick={() => go("my-applications/" + a.id)}>
    <div className="flex justify-between"><span><span className="font-mono">{a.app_no}</span> · {fmt.title(a.category)}{a.change_type !== "NONE" ? " / " + fmt.title(a.change_type) : ""}</span><Chip value={a.status === "IN_PROGRESS" ? a.current_stage : a.status} label={a.status === "IN_PROGRESS" ? "At " + fmt.stage(a.current_stage) : fmt.title(a.status)} /></div>
    <div className="text-[11px] text-slate-500 mt-0.5">{a.status === "IN_PROGRESS" ? "Expected stage completion by " + fmt.date(a.sla_due_at) + (a.sla.state === "OVERDUE" ? " (delayed; AICTE has been alerted)" : "") : a.status === "RETURNED" ? "Returned: " + a.return_reason : a.status === "APPROVED" ? "Approved " + fmt.date(a.decided_at) : ""}</div></div>);
}

function SubmitApplication({ user, go }) {
  const [category, setCategory] = useState("EOA"); const [change, setChange] = useState("NONE"); const [courses, setCourses] = useState("B.E./B.Tech - Computer Science & Engineering:120");
  const [err, setErr] = useState(null); const [busy, setBusy] = useState(false);
  const rules = useApi("/rules");
  const preview = rules.data && (() => { for (const r of rules.data.rules.routing) { const w = r.when; if ((!w.category || w.category === category) && (!w.change_type || w.change_type === change)) return r; } return { pipeline: rules.data.rules.default_pipeline, note: "Default" }; })();
  const submit = async () => {
    setBusy(true); setErr(null);
    try { const cs = courses.split("\n").filter(Boolean).map(l => { const [c, n] = l.split(":"); return { course: c.trim(), intake: parseInt(n || "60", 10) }; }); const a = await api.post("/applications", { category, change_type: change, details: { courses: cs } }); go("my-applications/" + a.id); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return (<div className="fade"><Section title="Submit application" />
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3"><Card title="Application details">
      <Field label="Category"><Sel value={category} onChange={setCategory} options={[["EOA", "Extension of Approval (EoA)"], ["NEW_INSTITUTION", "New institution"], ["CHANGE_OF_SITE", "Change of site"], ["CHANGE_OF_NAME", "Change of name"], ["CLOSURE", "Closure"]]} /></Field>
      <Field label="Change requested"><Sel value={change} onChange={setChange} options={[["NONE", "None"], ["INCREASE_INTAKE", "Increase in intake"], ["NEW_COURSE", "New course"], ["REDUCTION", "Reduction of intake"]]} /></Field>
      <Field label="Programmes (one per line, course:intake)"><textarea rows="4" className={inputCls} value={courses} onChange={e => setCourses(e.target.value)} /></Field>
      <ErrorBox error={err} /><Btn tone="primary" disabled={busy} onClick={submit}>Submit to AICTE</Btn></Card>
      <Card title="What will happen (auto-routing preview)">{preview && <div className="text-[12px]"><div><b>Pipeline:</b> {fmt.title(preview.pipeline)}</div><div className="text-slate-500">{preview.note}</div>
        <div className="mt-2">Stages: {rules.data.rules.pipelines[preview.pipeline].map(s => fmt.stage(s) + " (" + rules.data.rules.stages[s].sla_days + " d)").join(" → ")}</div>
        <div className="mt-3 text-slate-500">Your institution's compliance band decides the priority lane: Green Channel institutions get fast-track SLAs; statutory stages are never skipped.</div></div>}</Card></div></div>);
}

function MyApplications({ user, go, selectedId, refreshKey }) {
  const { data, error, reload } = useApi("/applications?status=IN_PROGRESS,RETURNED,APPROVED", [refreshKey]);
  return (<div className="fade"><Section title="My applications" right={<Btn tone="primary" small onClick={() => go("submit")}>New application</Btn>} /><ErrorBox error={error} />
    <Card pad={false}><Table rows={data} onRow={r => go("my-applications/" + r.id)} cols={[{ h: "App ID", r: r => <span className="font-mono text-[12px]">{r.app_no}</span> }, { h: "Category", r: r => fmt.title(r.category) + (r.change_type !== "NONE" ? " / " + fmt.title(r.change_type) : "") }, { h: "Submitted", r: r => fmt.date(r.submitted_at) }, { h: "Current stage", r: r => <Chip value={r.status === "IN_PROGRESS" ? r.current_stage : r.status} label={r.status === "IN_PROGRESS" ? fmt.stage(r.current_stage) : fmt.title(r.status)} /> }, { h: "Expected by", r: r => r.status === "IN_PROGRESS" ? fmt.date(r.sla_due_at) : "-" }, { h: "Priority lane", r: r => <Chip value={r.priority} /> }]} /></Card>
    {selectedId && <ApplicationDetail id={selectedId} user={user} onClose={() => go("my-applications")} onChanged={reload} />}</div>);
}

function VerifyPage({ code }) {
  const [c, setC] = useState(code || ""); const [res, setRes] = useState(null); const [busy, setBusy] = useState(false);
  const check = async (x) => { setBusy(true); try { setRes(await api.get("/verify/" + encodeURIComponent(x))); } catch (e) { setRes({ valid: false, message: e.message }); } finally { setBusy(false); } };
  useEffect(() => { if (code) check(code); }, [code]);
  return (<div className="min-h-screen bg-slate-100 flex items-start justify-center p-6"><div className="w-full max-w-xl">
    <div className="text-center mb-5"><div className="text-2xl font-extrabold tracking-wider text-navy-800">PRAVAH</div><div className="text-[12px] text-slate-500">AICTE approval letter verification (public) - prototype, synthetic data</div></div>
    <Card><div className="flex gap-2"><input className={inputCls} placeholder="Enter the verification code printed under the QR" value={c} onChange={e => setC(e.target.value.toUpperCase())} /><Btn tone="primary" disabled={!c || busy} onClick={() => check(c)}>Verify</Btn></div>
      {res && <div className={"mt-4 rounded-lg p-4 text-[13px] " + (res.valid ? "bg-green-50 border border-green-200" : "bg-red-50 border border-red-200")}>
        {res.valid ? <div><div className="text-green-800 font-bold text-[15px]">{"\u2713"} Genuine AICTE approval letter</div>
          <div className="mt-2"><b>{res.institution.name}</b> · {res.institution.pid}<div className="text-slate-600">{res.institution.district}, {res.institution.state} · {fmt.title(res.institution.type)}</div></div>
          <div className="mt-2">Letter <span className="font-mono">{res.letter_no}</span> · issued {fmt.date(res.issued_at)} · AY {res.academic_year} · {fmt.title(res.application.category)}</div>
          <table className="tbl w-full mt-2"><thead><tr><th>Approved programme</th><th>Intake</th></tr></thead><tbody>{res.courses.map((x, k) => <tr key={k}><td>{x.course}</td><td>{x.proposed_intake || x.intake}</td></tr>)}</tbody></table>
          <div className="text-[11px] text-slate-400 mt-2">Checked against AICTE records at {fmt.dt(res.verified_at)}.</div></div>
          : <div><div className="text-red-800 font-bold text-[15px]">{"\u2717"} Not verified</div><div className="text-slate-700 mt-1">{res.message}</div></div>}</div>}</Card>
    <div className="text-center mt-4"><a href="#/" className="text-[12px] text-blue-700 underline">Back to portal</a></div></div></div>);
}
