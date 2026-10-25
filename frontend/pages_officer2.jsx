/* Officer pages part 2: undertakings, documents, alerts, outbox, reports, audit, rules, institutions. */

function Undertakings({ user, refreshKey }) {
  const [status, setStatus] = useState("PENDING,OVERDUE,SUBMITTED");
  const { data, error, reload } = useApi("/undertakings?status=" + status, [refreshKey]);
  const [sel, setSel] = useState(null); const [verify, setVerify] = useState(null);
  const toast = useToast();
  const isInst = user.role === "INSTITUTION"; const isOfficer = ["REGIONAL_OFFICER", "BUREAU_OFFICER", "ADMIN"].includes(user.role);
  return (<div className="fade">{toast.el}
    <Section title="Time-bound undertakings & institutional compliance" right={<Sel value={status} onChange={setStatus} options={[["PENDING,OVERDUE,SUBMITTED", "Open"], ["OVERDUE", "Overdue"], ["SUBMITTED", "Evidence to verify"], ["VERIFIED", "Verified"], ["PENDING,OVERDUE,SUBMITTED,VERIFIED,REJECTED", "All"]]} />} />
    <ErrorBox error={error} />
    <Card pad={false}><Table rows={data} empty="No undertakings" cols={[
      { h: "Institution", r: r => <span>{r.institution_name}<div className="text-[11px] text-slate-400">{r.institution_pid} · {fmt.title(r.region)}</div></span> },
      { h: "Undertaking", r: r => <span><Chip tone="slate" label={fmt.title(r.category)} /> <span className="ml-1">{r.condition}</span></span> },
      { h: "Due", r: r => <span>{fmt.date(r.due_date)}<div className="text-[11px]">{r.days_to_due < 0 ? <span className="text-red-700 font-semibold">{-r.days_to_due} d overdue</span> : <span className="text-slate-500">in {r.days_to_due} d</span>}</div></span> },
      { h: "Status", r: r => <span><Chip value={r.status} />{r.escalated && <Chip tone="red" label="Escalated" />}</span> },
      { h: "Reminders", r: r => r.reminders_sent || 0 },
      { h: "Evidence", r: r => r.evidence ? <span className="text-[12px]">{r.evidence.filename}<div className="text-[11px] text-slate-400">{fmt.dt(r.evidence.submitted_at)}</div></span> : <span className="text-slate-300">-</span> },
      { h: "", r: r => <div className="flex gap-1">{isInst && ["PENDING", "OVERDUE"].includes(r.status) && <Btn small tone="primary" onClick={() => setSel(r)}>Upload evidence</Btn>}{isOfficer && r.status === "SUBMITTED" && <Btn small tone="ok" onClick={() => setVerify(r)}>Verify</Btn>}</div> },
    ]} /></Card>
    {sel && <EvidenceModal u={sel} onClose={() => setSel(null)} onDone={() => { setSel(null); reload(); toast.show("Evidence submitted - awaiting verification"); }} onErr={m => toast.show(m, "err")} />}
    {verify && <VerifyModal title={"Verify compliance evidence - " + verify.institution_name} item={verify} path={"/undertakings/" + verify.id + "/verify"} onClose={() => setVerify(null)} onDone={() => { setVerify(null); reload(); toast.show("Verification recorded"); }} onErr={m => toast.show(m, "err")}>
      <div className="text-[12px] mb-3"><b>{fmt.title(verify.category)}:</b> {verify.condition}<div className="text-slate-500 mt-1">Evidence: {verify.evidence && verify.evidence.filename} · {verify.evidence && verify.evidence.note}</div></div></VerifyModal>}
  </div>);
}
function EvidenceModal({ u, onClose, onDone, onErr }) {
  const [filename, setFilename] = useState(""); const [note, setNote] = useState("");
  return (<Modal title="Upload compliance evidence" onClose={onClose}>
    <div className="text-[12px] text-slate-700 mb-3"><b>{fmt.title(u.category)}:</b> {u.condition} · due {fmt.date(u.due_date)}</div>
    <Field label="Document (file name - upload simulated in prototype)"><input className={inputCls} placeholder="e.g. faculty_appointment_orders.pdf" value={filename} onChange={e => setFilename(e.target.value)} /></Field>
    <Field label="Note to the Regional Office"><input className={inputCls} value={note} onChange={e => setNote(e.target.value)} /></Field>
    <Btn tone="primary" disabled={!filename} onClick={async () => { try { await api.post("/undertakings/" + u.id + "/submit", { filename, note }); onDone(); } catch (e) { onErr(e.message); } }}>Submit</Btn></Modal>);
}
function VerifyModal({ title, path, onClose, onDone, onErr, children }) {
  const [remarks, setRemarks] = useState("");
  const send = async (accepted) => { try { await api.post(path, { accepted, remarks }); onDone(); } catch (e) { onErr(e.message); } };
  return (<Modal title={title} onClose={onClose}>{children}
    <Field label="Observation"><input className={inputCls} value={remarks} onChange={e => setRemarks(e.target.value)} /></Field>
    <div className="flex gap-2"><Btn tone="ok" onClick={() => send(true)}>Accept - compliance verified</Btn><Btn tone="danger" onClick={() => send(false)}>Not acceptable - ask to resubmit</Btn></div></Modal>);
}

function Documents({ user, refreshKey }) {
  const [status, setStatus] = useState("");
  const { data, error, reload } = useApi("/documents" + (status ? "?status=" + status : ""), [refreshKey]);
  const [renew, setRenew] = useState(null); const [verify, setVerify] = useState(null);
  const toast = useToast();
  const isInst = user.role === "INSTITUTION"; const isOfficer = ["REGIONAL_OFFICER", "BUREAU_OFFICER", "ADMIN"].includes(user.role);
  const rows = data && data.filter(d => d.status !== "SUPERSEDED");
  return (<div className="fade">{toast.el}
    <Section title="Lease & prescribed document validity" right={<Sel value={status} onChange={setStatus} all="All statuses" options={[["EXPIRED", "Expired"], ["EXPIRING", "Expiring"], ["RENEWAL_SUBMITTED", "Renewal to verify"], ["VALID", "Valid"]]} />} />
    <ErrorBox error={error} />
    <Card pad={false}><Table rows={rows} empty="No documents" cols={[
      { h: "Institution", r: r => <span>{r.institution_name}<div className="text-[11px] text-slate-400">{r.institution_pid} · {fmt.title(r.region)}</div></span> },
      { h: "Document", r: r => <span>{r.title}<div className="text-[11px] text-slate-400">{fmt.title(r.doc_type)} · ref {r.ref_no} · {r.issuing_authority}</div></span> },
      { h: "Valid till", r: r => <span>{fmt.date(r.valid_till)}<div className="text-[11px]">{r.days_to_expiry < 0 ? <span className="text-red-700 font-semibold">expired {-r.days_to_expiry} d ago</span> : <span className="text-slate-500">{r.days_to_expiry} d left</span>}</div></span> },
      { h: "Validity", r: r => <ValidityBar d={r} /> },
      { h: "Status", r: r => <Chip value={r.status} /> },
      { h: "Alerts sent", r: r => (r.alerts_sent || []).length ? (r.alerts_sent || []).map(w => "T-" + w + "d").join(", ") : <span className="text-slate-300">-</span> },
      { h: "Fingerprint", r: r => <span className="font-mono text-[10px] text-slate-400">{(r.sha256 || "").slice(0, 12)}</span> },
      { h: "", r: r => <div className="flex gap-1">{isInst && ["EXPIRING", "EXPIRED", "VALID"].includes(r.status) && <Btn small tone="primary" onClick={() => setRenew(r)}>Submit renewal</Btn>}{isOfficer && r.status === "RENEWAL_SUBMITTED" && <Btn small tone="ok" onClick={() => setVerify(r)}>Verify renewal</Btn>}</div> },
    ]} /></Card>
    {renew && <RenewModal d={renew} onClose={() => setRenew(null)} onDone={() => { setRenew(null); reload(); toast.show("Renewal submitted for verification"); }} onErr={m => toast.show(m, "err")} />}
    {verify && <VerifyModal title={"Verify renewed document - " + verify.institution_name} path={"/documents/" + verify.id + "/verify-renewal"} onClose={() => setVerify(null)} onDone={() => { setVerify(null); reload(); toast.show("Renewal verified; validity updated"); }} onErr={m => toast.show(m, "err")}>
      <div className="text-[12px] mb-3">{verify.title}<div className="text-slate-500">Submitted renewal: ref {verify.renewal && verify.renewal.ref_no} · valid till {verify.renewal && fmt.date(verify.renewal.valid_till)} · {verify.renewal && verify.renewal.filename}</div></div></VerifyModal>}
  </div>);
}
function ValidityBar({ d }) {
  const total = Math.max(1, (new Date(d.valid_till) - new Date(d.issued_on)) / 864e5);
  const left = Math.max(0, Math.min(1, d.days_to_expiry / total));
  const col = d.days_to_expiry < 0 ? "#DC2626" : d.days_to_expiry <= 90 ? "#F59E0B" : "#16A34A";
  return <div className="w-24 h-2 rounded bg-slate-100 overflow-hidden"><div className="h-full" style={{ width: (left * 100) + "%", background: col }}></div></div>;
}
function RenewModal({ d, onClose, onDone, onErr }) {
  const [ref, setRef] = useState(""); const [issued, setIssued] = useState(""); const [till, setTill] = useState(""); const [filename, setFilename] = useState("");
  return (<Modal title={"Submit renewed document - " + d.title} onClose={onClose}>
    <Field label="New reference number"><input className={inputCls} value={ref} onChange={e => setRef(e.target.value)} /></Field>
    <div className="grid grid-cols-2 gap-3"><Field label="Issued on"><input type="date" className={inputCls} value={issued} onChange={e => setIssued(e.target.value)} /></Field><Field label="Valid till"><input type="date" className={inputCls} value={till} onChange={e => setTill(e.target.value)} /></Field></div>
    <Field label="Scanned document (file name - upload simulated)"><input className={inputCls} value={filename} onChange={e => setFilename(e.target.value)} /></Field>
    <Btn tone="primary" disabled={!ref || !issued || !till} onClick={async () => { try { await api.post("/documents/" + d.id + "/renew", { ref_no: ref, issued_on: issued, valid_till: till, filename }); onDone(); } catch (e) { onErr(e.message); } }}>Submit renewal</Btn></Modal>);
}

function Alerts({ user, refreshKey }) {
  const [state, setState] = useState("OPEN,ACKNOWLEDGED"); const [sev, setSev] = useState(""); const [esc, setEsc] = useState(false);
  const { data, error, reload } = useApi("/alerts?state=" + state + (sev ? "&severity=" + sev : "") + (esc ? "&escalated=true" : "") + "&limit=300", [refreshKey]);
  const toast = useToast();
  const canClose = ["REGIONAL_OFFICER", "BUREAU_OFFICER", "MEMBER_SECRETARY", "ADMIN"].includes(user.role);
  const act = async (id, what) => { try { await api.post("/alerts/" + id + "/" + what); reload(); } catch (e) { toast.show(e.message, "err"); } };
  return (<div className="fade">{toast.el}
    <Section title="Alerts & escalations" right={<div className="flex gap-2 items-center"><label className="text-[12px] flex items-center gap-1"><input type="checkbox" checked={esc} onChange={e => setEsc(e.target.checked)} /> escalated only</label>
      <Sel value={sev} onChange={setSev} all="All severities" options={[["CRITICAL", "Critical"], ["WARNING", "Warning"], ["INFO", "Info"]]} />
      <Sel value={state} onChange={setState} options={[["OPEN,ACKNOWLEDGED", "Open"], ["OPEN", "Unacknowledged"], ["CLOSED", "Closed"], ["OPEN,ACKNOWLEDGED,CLOSED", "All"]]} /></div>} />
    <ErrorBox error={error} />
    {!data ? <Spinner /> : data.length === 0 ? <Card><Empty text="No alerts in this view" /></Card> : <div className="space-y-2">{data.map(a => <div key={a.id} className="rounded-lg bg-white border border-slate-200 px-4 py-3 flex items-start justify-between gap-3">
      <div className="text-[12px]"><div className="flex items-center gap-1.5 flex-wrap"><Chip value={a.severity} /><Chip tone="slate" label={fmt.title(a.kind)} />{a.escalation_level > 0 && <Chip tone="red" label={"Escalated L" + a.escalation_level + (a.escalated_to_role ? " → " + fmt.title(a.escalated_to_role) : "")} />}<Chip value={a.state} /></div>
        <div className="font-semibold text-slate-800 mt-1">{a.title}</div><div className="text-slate-600">{a.message}</div>
        <div className="text-[11px] text-slate-400 mt-1">{a.institution_name ? a.institution_name + " · " : ""}{fmt.dt(a.created_at)}{a.due_at ? " · due " + fmt.date(a.due_at) : ""} · {a.notifications} notification(s) sent{a.acknowledged_by ? " · acknowledged by " + a.acknowledged_by : ""}</div></div>
      <div className="flex gap-1 shrink-0">{a.state === "OPEN" && <Btn small onClick={() => act(a.id, "ack")}>Acknowledge</Btn>}{canClose && a.state !== "CLOSED" && <Btn small tone="ok" onClick={() => act(a.id, "close")}>Close</Btn>}</div></div>)}</div>}
  </div>);
}

function Outbox({ refreshKey }) {
  const [channel, setChannel] = useState("");
  const { data, error } = useApi("/notifications?limit=200" + (channel ? "&channel=" + channel : ""), [refreshKey]);
  return (<div className="fade"><Section title="Notification outbox (Email · SMS · WhatsApp · in-app)" right={<Sel value={channel} onChange={setChannel} all="All channels" options={[["EMAIL", "Email"], ["SMS", "SMS"], ["WHATSAPP", "WhatsApp"], ["IN_APP", "In-app"]]} />} />
    <ErrorBox error={error} />
    {data && <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">{Object.entries(data.by_channel).map(([c, n]) => <KPI key={c} label={fmt.title(c) + " messages"} value={n} tone={{ EMAIL: "blue", SMS: "amber", WHATSAPP: "green", IN_APP: "slate" }[c]} />)}</div>}
    <div className="text-[11px] text-slate-500 mb-2">Channels are simulated in the prototype (stored + written to data/outbox.log). Production: NIC e-mail, SMS gateway, WhatsApp Business API via Celery workers; digest for routine, instant for critical.</div>
    <Card pad={false}><Table dense rows={data && data.items} cols={[{ h: "Sent", r: r => fmt.dt(r.sent_at) }, { h: "Channel", r: r => <Chip tone={{ EMAIL: "blue", SMS: "amber", WHATSAPP: "green", IN_APP: "slate" }[r.channel]} label={fmt.title(r.channel)} /> }, { h: "Recipient", r: r => <span>{r.recipient}<div className="text-[11px] text-slate-400">{fmt.title(r.recipient_role)}</div></span> }, { h: "Message", k: "body" }, { h: "Status", r: r => <Chip tone="green" label={r.status} /> }]} /></Card></div>);
}

function Reports({ user }) {
  const { data, error } = useApi("/reports/region-performance");
  const rules = useApi("/rules");
  return (<div className="fade"><Section title="Reports & analytics" right={<a className="text-[12px] text-blue-700 underline" href={"/api/reports/export.csv"} onClick={async e => { e.preventDefault(); const r = await fetch("/api/reports/export.csv", { headers: { Authorization: "Bearer " + api.token() } }); const b = await r.blob(); const u = URL.createObjectURL(b); const a = document.createElement("a"); a.href = u; a.download = "pravah_pendency.csv"; a.click(); }}>Export pendency CSV</a>} />
    <ErrorBox error={error} />
    <Card title="Region-wise processing performance" pad={false}><Table dense rows={data} cols={[
      { h: "Region", k: "label" }, { h: "Institutions", k: "institutions" }, { h: "Received", k: "received" }, { h: "Pending", k: "pending" },
      { h: "Overdue", r: r => <span className={r.overdue ? "text-red-700 font-semibold" : ""}>{r.overdue}</span> }, { h: "Returned", k: "returned" }, { h: "Approved", k: "approved" },
      { h: "Avg processing days", r: r => r.avg_processing_days ?? "-" }, { h: "SLA breaches", k: "sla_breaches" }, { h: "Undertakings overdue", k: "undertakings_overdue" }, { h: "Docs expired", k: "documents_expired" }, { h: "Open escalations", r: r => <span className={r.open_escalations ? "text-red-700 font-semibold" : ""}>{r.open_escalations}</span> }]} /></Card>
    {data && <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3"><Card title="Pending vs overdue by Region"><ChartBox labels={data.map(r => r.label.replace(/ RO.*$/, ""))} data={data.map(r => r.pending)} height={200} /></Card>
      <Card title="Average processing days by Region"><ChartBox labels={data.map(r => r.label.replace(/ RO.*$/, ""))} data={data.map(r => r.avg_processing_days || 0)} colors="#0F766E" height={200} /></Card></div>}
    {rules.data && <Card title={"Prescribed stage timelines in force (" + rules.data.rules.version + ")"} className="mt-3" pad={false}><Table dense rows={Object.entries(rules.data.rules.stages).map(([k, v]) => ({ id: k, stage: v.label, sla: v.sla_days, owner: v.owner_role }))} cols={[{ h: "Stage", k: "stage" }, { h: "SLA (days)", k: "sla" }, { h: "Owner role", r: r => fmt.title(r.owner) }]} /></Card>}
  </div>);
}

function Audit({ refreshKey }) {
  const [action, setAction] = useState("");
  const { data, error } = useApi("/audit?limit=200" + (action ? "&action=" + action : ""), [refreshKey]);
  return (<div className="fade"><Section title="Audit trail (hash-chained)" right={data && <div className={"text-[12px] font-semibold px-3 py-1 rounded-md " + (data.chain.intact ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800")}>{data.chain.intact ? "Chain intact" : "Chain BROKEN"} · {data.chain.entries} entries · head {data.chain.head_hash.slice(0, 12)}...</div>} />
    <ErrorBox error={error} />
    <div className="mb-2"><input className={inputCls + " w-72"} placeholder="Filter by action, e.g. STAGE_ADVANCED" value={action} onChange={e => setAction(e.target.value.toUpperCase())} /></div>
    <Card pad={false}><Table dense rows={data && data.items} cols={[{ h: "#", k: "id" }, { h: "Time", r: r => fmt.dt(r.ts) }, { h: "Actor", r: r => <span>{r.actor}<div className="text-[11px] text-slate-400">{fmt.title(r.actor_role)}</div></span> }, { h: "Action", r: r => <Chip tone="slate" label={fmt.title(r.action)} /> }, { h: "Entity", r: r => (r.entity_type || "") + " " + (r.entity_id || "") }, { h: "Details", r: r => <span className="font-mono text-[11px] text-slate-600 break-all">{JSON.stringify(r.details)}</span> }, { h: "Hash", r: r => <span className="font-mono text-[10px] text-slate-400">{(r.hash || "").slice(0, 10)}<br />{"\u2191 " + (r.prev_hash || "").slice(0, 10)}</span> }]} /></Card></div>);
}

function Rules({ user }) {
  const { data, error, reload } = useApi("/rules");
  const [text, setText] = useState(null); const [msg, setMsg] = useState(null);
  useEffect(() => { if (data && text === null) setText(JSON.stringify(data.rules, null, 2)); }, [data]);
  const setSla = (k, v) => { const r = JSON.parse(text); r.stages[k].sla_days = parseInt(v || 0, 10); setText(JSON.stringify(r, null, 2)); };
  const save = async () => { try { const r = await api.put("/rules", { rules: JSON.parse(text) }); setMsg("Saved as " + r.version + " (previous versions retained, change audited)"); reload(); } catch (e) { setMsg("Error: " + e.message); } };
  if (error) return <ErrorBox error={error} />;
  if (!data || text === null) return <Spinner />;
  const parsed = (() => { try { return JSON.parse(text); } catch (e) { return null; } })();
  return (<div className="fade"><Section title="Configurable rules - stages, SLAs, routing, escalation" right={<Chip tone="navy" label={data.rules.version} />} />
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
      <Card title="Stage SLAs (days) - edit without code">{parsed ? Object.entries(parsed.stages).map(([k, v]) => <div key={k} className="flex items-center justify-between py-1.5 text-[12px] border-b border-slate-100"><span>{v.label}<div className="text-[11px] text-slate-400">{fmt.title(v.owner_role)}</div></span><input type="number" className="w-20 rounded border border-slate-300 px-2 py-1 text-right" value={v.sla_days} onChange={e => setSla(k, e.target.value)} disabled={user.role !== "ADMIN"} /></div>) : <div className="text-red-600 text-[12px]">JSON invalid</div>}
        <div className="mt-3 text-[12px]"><b>Pipelines</b>{parsed && Object.entries(parsed.pipelines).map(([k, v]) => <div key={k} className="text-slate-600">{fmt.title(k)}: {v.map(fmt.stage).join(" → ")}</div>)}</div>
        <div className="mt-3 text-[12px]"><b>Escalation ladder</b>{parsed && parsed.escalation.levels.map((l, i) => <div key={i} className="text-slate-600">{l.label}: after {l.after_overdue_days} d overdue</div>)}</div>
        <div className="mt-3"><Btn tone="primary" disabled={user.role !== "ADMIN" || !parsed} onClick={save}>Save as new version</Btn>{msg && <div className="text-[12px] mt-2 text-slate-700">{msg}</div>}{user.role !== "ADMIN" && <div className="text-[11px] text-slate-400 mt-1">Only administrators can change rules.</div>}</div>
        <div className="mt-3 text-[11px] text-slate-500"><b>Versions:</b> {data.history.map(h => h.version + (h.active ? " (active)" : "")).join(", ")}</div></Card>
      <Card title="Rule set (JSON) - routing conditions, reminder windows, experts roster" className="lg:col-span-2"><textarea className={inputCls + " font-mono text-[11px]"} rows="30" value={text} onChange={e => setText(e.target.value)} disabled={user.role !== "ADMIN"} /></Card>
    </div></div>);
}

function Institutions({ go, selectedId, refreshKey }) {
  const { data, error } = useApi("/institutions", [refreshKey]);
  return (<div className="fade"><Section title="Institutions - compliance score & Green Channel" />
    <ErrorBox error={error} />
    <Card pad={false}><Table rows={data} onRow={r => go("institutions/" + r.id)} cols={[
      { h: "PID", r: r => <span className="font-mono text-[12px]">{r.pid}</span> }, { h: "Institution", r: r => <span>{r.name}<div className="text-[11px] text-slate-400">{fmt.title(r.type)} · {r.district}, {r.state} · est. {r.established_year}</div></span> },
      { h: "Region", r: r => r.region_label }, { h: "Compliance score", r: r => <div className="flex items-center gap-2"><div className="w-24 h-2 rounded bg-slate-100 overflow-hidden"><div className="h-full" style={{ width: r.compliance_score + "%", background: { GREEN: "#16A34A", AMBER: "#F59E0B", RED: "#DC2626" }[r.compliance_band] }}></div></div><b className="text-[12px]">{r.compliance_score}</b></div> },
      { h: "Band", r: r => <Chip value={r.compliance_band} label={r.compliance_band === "GREEN" ? "Green Channel" : r.compliance_band === "AMBER" ? "Standard" : "High risk"} /> }, { h: "Pending apps", k: "pending_applications" }, { h: "Open alerts", r: r => <span className={r.open_alerts ? "text-red-700 font-semibold" : ""}>{r.open_alerts}</span> }]} /></Card>
    {selectedId && <InstitutionDetail id={selectedId} onClose={() => go("institutions")} go={go} />}</div>);
}
function InstitutionDetail({ id, onClose, go }) {
  const { data, error } = useApi("/institutions/" + id);
  if (error) return <Modal title="Institution" onClose={onClose}><ErrorBox error={error} /></Modal>;
  if (!data) return <Modal title="Institution" onClose={onClose}><Spinner /></Modal>;
  const i = data;
  return (<Modal wide title={i.name + " (" + i.pid + ")"} onClose={onClose}>
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-[12px]">
      <div><div className="rounded-lg border border-slate-200 p-3"><div className="text-slate-500">Compliance score</div><div className="text-3xl font-bold">{i.compliance_score} <Chip value={i.compliance_band} /></div>
        <ul className="mt-2 space-y-1">{i.score_breakdown.length === 0 && <li className="text-green-700">No deductions - fully compliant</li>}{i.score_breakdown.map((b, k) => <li key={k} className="flex justify-between"><span>{b.factor} ×{b.count}</span><b className="text-red-700">{b.delta}</b></li>)}</ul></div>
        <ReadinessCard r={i.readiness} /></div>
      <div className="md:col-span-2 space-y-3">
        <div><b>Applications</b><Table dense rows={i.applications} onRow={r => { onClose(); go("applications/" + r.id); }} cols={[{ h: "App", r: r => <span className="font-mono">{r.app_no}</span> }, { h: "Category", r: r => fmt.title(r.category) }, { h: "Stage", r: r => <Chip value={r.status === "IN_PROGRESS" ? r.current_stage : r.status} label={r.status === "IN_PROGRESS" ? fmt.stage(r.current_stage) : fmt.title(r.status)} /> }, { h: "SLA", r: r => r.status === "IN_PROGRESS" ? <Chip value={r.sla.state} /> : "-" }]} /></div>
        <div><b>Prescribed documents</b><Table dense rows={i.documents.filter(d => d.status !== "SUPERSEDED")} cols={[{ h: "Document", k: "title" }, { h: "Valid till", r: r => fmt.date(r.valid_till) }, { h: "Status", r: r => <Chip value={r.status} /> }]} /></div>
        <div><b>Undertakings</b><Table dense rows={i.undertakings} cols={[{ h: "Condition", k: "condition" }, { h: "Due", r: r => fmt.date(r.due_date) }, { h: "Status", r: r => <Chip value={r.status} /> }]} /></div>
      </div></div></Modal>);
}
function ReadinessCard({ r }) {
  if (!r) return null;
  return (<div className="rounded-lg border border-slate-200 p-3 mt-3"><div className="flex items-center justify-between"><b>Pre-submission self-scrutiny</b><Chip value={r.overall} label={r.overall === "GREEN" ? "Ready" : r.overall === "AMBER" ? "Attention" : "Not ready"} /></div>
    <ul className="mt-2 space-y-1.5">{r.items.map((it, k) => <li key={k} className="flex gap-2 items-start"><span className={"mt-1 h-2.5 w-2.5 rounded-full shrink-0 " + ({ GREEN: "bg-green-500", AMBER: "bg-amber-500", RED: "bg-red-500" }[it.status] || "bg-slate-300")}></span><span><b>{it.item}</b><div className="text-slate-500">{it.detail}</div></span></li>)}</ul></div>);
}
