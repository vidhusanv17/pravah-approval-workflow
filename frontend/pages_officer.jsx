/* Officer-facing pages: overview, applications, EVC, undertakings, documents, alerts, outbox, reports, audit, rules, institutions. */

// ------------------------------------------------------------------ Overview
function Overview({ user, go, refreshKey }) {
  const { data, error } = useApi("/dashboard/summary", [refreshKey]);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;
  const k = data.kpis;
  const roleTitle = user.role === "REGIONAL_OFFICER" ? "Regional Officer Dashboard - " + (user.region_label || "") : user.role === "BUREAU_OFFICER" ? "Approval Bureau Dashboard - all Regions" : user.role === "MEMBER_SECRETARY" ? "Member Secretary - national view" : "Overview";
  return (<div className="fade">
    <Section title={roleTitle} right={<div className="text-[11px] text-slate-500 text-right">Rules {data.rules_version} &middot; as of {fmt.dt(data.as_of)}</div>} />
    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3 mb-4">
      <KPI label="Pending applications (all stages)" value={k.pending} tone="blue" onClick={() => go("applications")} />
      <KPI label="Overdue - prescribed timeline breached" value={k.overdue} tone="red" sub={k.due_soon + " due within 2 days"} onClick={() => go("applications/overdue")} />
      <KPI label="EVC visits due this week" value={k.evc_due_week} tone="purple" sub={k.evc_queue + " in EVC queue"} onClick={() => go("evc")} />
      <KPI label="Undertakings due in 30 days" value={k.undertakings_due_30} tone="amber" sub={k.undertakings_overdue + " overdue · " + k.undertakings_to_verify + " to verify"} onClick={() => go("undertakings")} />
      <KPI label="Documents expiring / expired" value={k.docs_expiring_90 + " / " + k.docs_expired} tone="amber" onClick={() => go("documents")} />
      <KPI label="Open escalations" value={k.escalations} tone="red" sub={k.open_alerts + " open alerts"} onClick={() => go("alerts")} />
    </div>
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
      <Card title="Applications approaching / exceeding prescribed timelines" className="xl:col-span-2" pad={false}>
        <Table dense rows={data.attention} onRow={r => go("applications/" + r.id)} cols={[
          { h: "App ID", r: r => <span className="font-mono text-[12px]">{r.app_no}</span> },
          { h: "Institution", r: r => <span>{r.institution_name}<div className="text-[11px] text-slate-400">{r.institution_pid} · {fmt.title(r.category)}{r.change_type !== "NONE" ? " · " + fmt.title(r.change_type) : ""}</div></span> },
          { h: "Stage", r: r => <Chip value={r.current_stage} label={fmt.stage(r.current_stage)} /> },
          { h: "Ageing", r: r => fmt.days(r.ageing_days) },
          { h: "SLA", r: r => <Chip value={r.sla.state} label={r.sla.state === "OVERDUE" ? "Overdue " + r.sla.days + " d" + (r.escalation_level ? " · L" + r.escalation_level : "") : r.sla.state === "DUE_SOON" ? "Due in " + r.sla.days + " d" : "On track"} /> },
          { h: "Priority", r: r => r.priority !== "NORMAL" ? <Chip value={r.priority} /> : <span className="text-slate-300">-</span> },
        ]} />
      </Card>
      <div className="space-y-3">
        <Card title="Escalations & alerts today" right={<a href="#/alerts" className="text-[11px] text-blue-700">all alerts</a>}>
          {data.alerts_today.length === 0 && <Empty text="No new alerts today - use the demo clock to move time forward" />}
          <ul className="divide-y divide-slate-100">{data.alerts_today.slice(0, 6).map(a => <li key={a.id} className="py-2 text-[12px]"><Chip value={a.severity} /> <span className="ml-1 text-slate-800">{a.title}</span><div className="text-[11px] text-slate-400 mt-0.5">{a.escalated_to_role ? "Escalated to " + fmt.title(a.escalated_to_role) + " · " : ""}{fmt.dt(a.created_at)}</div></li>)}</ul>
        </Card>
        <Card title="Stage-wise pendency"><Bars items={data.stage_pendency.map(s => ({ label: s.label, count: s.count, color: { SCRUTINY: "#2563EB", EVC: "#6D28D9", SAC_SHC: "#0F766E", RETURNED: "#F59E0B", APPROVAL: "#1E3A8A", RE_SCRUTINY: "#3B82F6" }[s.stage] }))} /></Card>
      </div>
    </div>
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
      <Card title="Application ageing"><ChartBox labels={data.ageing.map(a => a.bucket)} data={data.ageing.map(a => a.count)} colors={["#16A34A", "#2563EB", "#F59E0B", "#DC2626"]} height={180} /></Card>
      <Card title="Pendency by Region"><ChartBox labels={data.region_pendency.map(r => r.label.replace(/ RO.*$/, ""))} data={data.region_pendency.map(r => r.count)} height={180} /></Card>
      <Card title="Region performance (approved cases)">
        <Table dense rows={Object.values(data.region_performance).sort((a, b) => b.pending - a.pending)} cols={[
          { h: "Region", r: r => r.label.replace(/ RO.*$/, "") }, { h: "Pending", k: "pending" }, { h: "Overdue", r: r => <span className={r.overdue ? "text-red-700 font-semibold" : ""}>{r.overdue}</span> }, { h: "Approved", k: "approved" }, { h: "Avg days", r: r => r.avg_days ?? "-" }]} />
      </Card>
    </div>
  </div>);
}

// ------------------------------------------------------------------ Applications
function Applications({ user, go, selectedId, filter, refreshKey }) {
  const [status, setStatus] = useState(filter === "overdue" ? "IN_PROGRESS" : "IN_PROGRESS,RETURNED");
  const [stage, setStage] = useState("");
  const [q, setQ] = useState("");
  const overdue = filter === "overdue";
  const path = "/applications?status=" + status + (stage ? "&stage=" + stage : "") + (overdue ? "&overdue=true" : "") + (q ? "&q=" + encodeURIComponent(q) : "");
  const { data, error, reload } = useApi(path, [refreshKey]);
  return (<div className="fade">
    <Section title={overdue ? "Overdue applications" : "Applications"} right={<div className="flex gap-2 items-center">
      <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search app no / institution / PID" className={inputCls + " w-64"} />
      <Sel value={status} onChange={setStatus} options={[["IN_PROGRESS,RETURNED", "Active"], ["IN_PROGRESS", "In progress"], ["RETURNED", "Returned"], ["APPROVED", "Approved"], ["IN_PROGRESS,RETURNED,APPROVED", "All"]]} />
      <Sel value={stage} onChange={setStage} all="All stages" options={[["SCRUTINY", "Scrutiny"], ["RE_SCRUTINY", "Re-scrutiny"], ["EVC", "EVC"], ["SAC_SHC", "SAC / SHC"], ["APPROVAL", "Approval"]]} />
    </div>} />
    <ErrorBox error={error} />
    <Card pad={false}>
      <Table rows={data} onRow={r => go("applications/" + r.id)} empty="No applications match" cols={[
        { h: "App ID", r: r => <span className="font-mono text-[12px]">{r.app_no}</span> },
        { h: "Institution", r: r => <span>{r.institution_name}<div className="text-[11px] text-slate-400">{r.institution_pid} · {fmt.title(r.region)}</div></span> },
        { h: "Category", r: r => <span>{fmt.title(r.category)}{r.change_type !== "NONE" && <div className="text-[11px] text-slate-400">{fmt.title(r.change_type)}</div>}</span> },
        { h: "Pipeline", r: r => <span className="text-[11px] text-slate-600">{fmt.title(r.pipeline)}</span> },
        { h: "Stage", r: r => r.status === "RETURNED" ? <Chip value="RETURNED" /> : r.status === "APPROVED" ? <Chip value="APPROVED" /> : <Chip value={r.current_stage} label={fmt.stage(r.current_stage)} /> },
        { h: "Submitted", r: r => fmt.date(r.submitted_at) }, { h: "Ageing", r: r => fmt.days(r.ageing_days) },
        { h: "SLA", r: r => r.status !== "IN_PROGRESS" ? <span className="text-slate-300">-</span> : <Chip value={r.sla.state} label={r.sla.state === "OVERDUE" ? "Overdue " + r.sla.days + " d" : r.sla.state === "DUE_SOON" ? "Due in " + r.sla.days + " d" : "On track · " + r.sla.days + " d"} /> },
        { h: "Priority", r: r => r.priority !== "NORMAL" ? <Chip value={r.priority} /> : <span className="text-slate-300">Normal</span> },
        { h: "Esc.", r: r => r.escalation_level ? <span className="text-red-700 font-bold text-[12px]">L{r.escalation_level}</span> : "" },
      ]} />
    </Card>
    {selectedId && <ApplicationDetail id={selectedId} user={user} onClose={() => go(overdue ? "applications/overdue" : "applications")} onChanged={reload} />}
  </div>);
}

function ApplicationDetail({ id, user, onClose, onChanged }) {
  const { data, error, reload } = useApi("/applications/" + id);
  const [mode, setMode] = useState(null);
  const [text, setText] = useState("");
  const [summary, setSummary] = useState(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const act = async (path, body) => {
    setBusy(true);
    try { await api.post("/applications/" + id + "/" + path, body); toast.show("Action recorded in the audit trail"); setMode(null); setText(""); reload(); onChanged && onChanged(); }
    catch (e) { toast.show(e.message, "err"); } finally { setBusy(false); }
  };
  if (error) return <Modal title="Application" onClose={onClose}><ErrorBox error={error} /></Modal>;
  if (!data) return <Modal title="Application" onClose={onClose}><Spinner /></Modal>;
  const a = data;
  const stages = a.pipeline_stages;
  return (<Modal wide title={"Application " + a.app_no} onClose={onClose}>
    {toast.el}
    <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
      <div><div className="text-[15px] font-semibold text-slate-900">{a.institution.name}</div>
        <div className="text-[12px] text-slate-500">{a.institution.pid} · {a.institution.district}, {a.institution.state} · {fmt.title(a.region)} · {fmt.title(a.category)}{a.change_type !== "NONE" ? " / " + fmt.title(a.change_type) : ""} · AY {a.academic_year}</div>
        <div className="text-[11px] text-slate-400 mt-1">Routing: {fmt.title(a.pipeline)} - {a.routing_note}</div></div>
      <div className="flex gap-1.5 items-center"><Chip value={a.status} />{a.priority !== "NORMAL" && <Chip value={a.priority} />}
        {a.status === "IN_PROGRESS" && <Chip value={a.sla.state} label={a.sla.state === "OVERDUE" ? "Overdue " + a.sla.days + " d" : a.sla.state === "DUE_SOON" ? "Due in " + a.sla.days + " d" : "On track · " + a.sla.days + " d left"} />}
        {a.escalation_level > 0 && <Chip tone="red" label={"Escalated L" + a.escalation_level} />}</div>
    </div>
    <div className="rounded-lg bg-slate-50 border border-slate-200 p-4 mb-4"><Stepper stages={stages} current={a.current_stage === "RE_SCRUTINY" ? stages[a.stage_index].key : a.current_stage} status={a.status} />
      {a.status === "RETURNED" && <div className="mt-3 text-[12px] text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-2"><b>Returned to institution</b> (return #{a.return_count}): {a.return_reason}</div>}
      {a.current_stage === "RE_SCRUTINY" && <div className="mt-3 text-[12px] text-blue-800">Resubmitted - under re-scrutiny (SLA {fmt.date(a.sla_due_at)})</div>}</div>
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="md:col-span-2">
        <h4 className="text-[12px] font-semibold text-slate-700 mb-2">Movement history (audit-linked)</h4>
        <ol className="relative border-l border-slate-200 ml-2 space-y-3">{a.history.map(h => <li key={h.id} className="ml-4 text-[12px]">
          <span className={"absolute -left-1.5 mt-1 h-3 w-3 rounded-full " + (h.breached ? "bg-red-500" : h.exited_at ? "bg-green-500" : "bg-blue-500")}></span>
          <div><b>{fmt.stage(h.stage)}</b> <span className="text-slate-500">· {h.action === "ENTERED" && !h.exited_at ? "in progress" : fmt.title(h.action)}{h.breached ? " · SLA breached" : ""}</span></div>
          <div className="text-slate-500">{fmt.dt(h.entered_at)}{h.exited_at ? " → " + fmt.dt(h.exited_at) : ""}{h.sla_days ? " · SLA " + h.sla_days + " d" : ""}{h.actor ? " · " + h.actor : ""}</div>
          {h.remarks && <div className="text-slate-700 italic">"{h.remarks}"</div>}</li>)}</ol>
        {a.evc && <div className="mt-4 rounded-lg border border-violet-200 bg-violet-50 p-3 text-[12px]"><b className="text-violet-900">Expert Visit Committee</b> <Chip value={a.evc.status} />
          <div className="text-slate-700 mt-1">{a.evc.status === "QUEUED" ? "To be scheduled by " + fmt.date(a.evc.due_by) : a.evc.status === "SCHEDULED" ? "Visit on " + fmt.date(a.evc.scheduled_on) : "Report submitted " + fmt.dt(a.evc.report_submitted_at) + " · outcome " + fmt.title(a.evc.outcome)}</div>
          {a.evc.members && a.evc.members.length > 0 && <div className="text-slate-500">Members: {a.evc.members.map(m => m.name).join(", ")}</div>}</div>}
        {a.letter && <div className="mt-4 rounded-lg border border-green-200 bg-green-50 p-3 text-[12px] flex gap-4 items-center">
          <img src={"/api/letters/" + a.id + "/qr.png"} alt="QR" className="h-24 w-24 rounded bg-white border" />
          <div><b className="text-green-900">Approval letter issued</b><div>Letter no. <span className="font-mono">{a.letter.letter_no}</span> · {fmt.date(a.letter.issued_at)}</div>
            <div>Public verification code <span className="font-mono font-bold">{a.letter.verify_code}</span> · <a className="text-blue-700 underline" href={"#/verify/" + a.letter.verify_code}>open verify page</a></div>
            <div className="mt-1"><a className="text-blue-700 underline" href={"/api/letters/" + a.id + "/pdf"} target="_blank">Download letter PDF (auto-generated)</a></div></div></div>}
      </div>
      <div>
        <h4 className="text-[12px] font-semibold text-slate-700 mb-2">Actions</h4>
        <div className="space-y-2">
          {a.can_act.advance && <Btn tone="primary" onClick={() => setMode("advance")}>{a.current_stage === "APPROVAL" ? "Grant approval & issue letter" : "Complete " + fmt.stage(a.current_stage) + " → next stage"}</Btn>}
          {a.can_act.return && <Btn tone="amber" onClick={() => setMode("return")}>Return to institution (reason required)</Btn>}
          {a.can_act.resubmit && <Btn tone="primary" onClick={() => setMode("resubmit")}>Rectify & resubmit</Btn>}
          {a.status === "IN_PROGRESS" && !a.can_act.advance && <div className="text-[11px] text-slate-500">Current stage is owned by <b>{fmt.title(a.can_act.owner_role)}</b>; your role can only view{a.can_act.return ? " or return" : ""}.</div>}
          <Btn onClick={async () => setSummary(await api.get("/applications/" + id + "/summary"))}>Electronic case summary</Btn>
          <div className="text-[11px] text-slate-400 pt-2">Open alerts on this file: {a.alerts.filter(x => x.state !== "CLOSED").length}</div>
          <ul className="text-[11px] text-slate-600 space-y-1">{a.alerts.slice(0, 4).map(x => <li key={x.id}><Chip value={x.severity} /> {x.title}</li>)}</ul>
        </div>
        {mode && <div className="mt-3 rounded-lg border border-slate-200 p-3">
          <Field label={mode === "return" ? "Reason for return (recorded, mandatory)" : "Remarks / observations"}><textarea className={inputCls} rows="3" value={text} onChange={e => setText(e.target.value)} /></Field>
          <div className="flex gap-2"><Btn tone={mode === "return" ? "amber" : "primary"} disabled={busy} onClick={() => act(mode, mode === "return" ? { reason: text } : { remarks: text })}>Confirm</Btn><Btn onClick={() => setMode(null)}>Cancel</Btn></div>
          <div className="text-[11px] text-slate-400 mt-2">The system routes and reminds; this authorised action is what moves the file.</div></div>}
      </div>
    </div>
    {summary && <CaseSummary s={summary} onClose={() => setSummary(null)} />}
  </Modal>);
}

function CaseSummary({ s, onClose }) {
  const p = s.pending_items;
  return (<Modal title={"Electronic case summary - " + s.application.app_no} onClose={onClose}>
    <div className="text-[12px] space-y-2">
      <div className="rounded-md px-3 py-2 border border-slate-200"><b>System recommendation:</b> <Chip value={s.recommendation.level} /> <span className="ml-1">{s.recommendation.text}</span></div>
      <div><b>Institution:</b> {s.institution.name} ({s.institution.pid}) · compliance {s.institution.compliance_score}/100 <Chip value={s.institution.compliance_band} /></div>
      <div><b>Pipeline:</b> {fmt.title(s.application.pipeline)} · <b>Stage:</b> {fmt.stage(s.application.current_stage)} · <b>Ageing:</b> {s.ageing_days} d · <b>SLA:</b> {s.sla_status.state}</div>
      <div><b>Pending items:</b> {p.undertakings_overdue.length} overdue undertakings, {p.undertakings_pending.length} pending, {p.documents_expired.length} expired documents, {p.documents_expiring.length} expiring</div>
      {p.documents_expired.map(d => <div key={d.id} className="text-red-700">· Expired: {d.title} (till {fmt.date(d.valid_till)})</div>)}
      {p.undertakings_overdue.map(u => <div key={u.id} className="text-red-700">· Overdue undertaking: {u.condition} (due {fmt.date(u.due_date)})</div>)}
      <div className="text-slate-400 pt-2">Generated {fmt.dt(s.generated_at)} · advisory only; statutory scrutiny and decisions remain with the competent authority.</div>
    </div></Modal>);
}

// ------------------------------------------------------------------ EVC
function EVC({ user, refreshKey }) {
  const { data, error, reload } = useApi("/evc/queue", [refreshKey]);
  const [tab, setTab] = useState("QUEUED");
  const [sched, setSched] = useState(null);
  const [done, setDone] = useState(null);
  const toast = useToast();
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;
  const rows = data.visits.filter(v => v.status === tab);
  const canSchedule = ["REGIONAL_OFFICER", "BUREAU_OFFICER", "ADMIN"].includes(user.role);
  const canComplete = ["EVC_MEMBER", "REGIONAL_OFFICER", "ADMIN"].includes(user.role);
  return (<div className="fade">{toast.el}
    <Section title="Expert Visit Committee - scheduling & timelines" right={<div className="flex gap-1">{["QUEUED", "SCHEDULED", "COMPLETED"].map(t => <button key={t} onClick={() => setTab(t)} className={"px-3 py-1 rounded-md text-[12px] " + (tab === t ? "bg-navy-800 text-white" : "bg-white border border-slate-300 text-slate-700")}>{fmt.title(t)} ({data.visits.filter(v => v.status === t).length})</button>)}</div>} />
    {data.clusters.length > 0 && tab === "QUEUED" && <div className="mb-3 rounded-lg border border-violet-200 bg-violet-50 px-4 py-2 text-[12px] text-violet-900"><b>Geo-clustering suggestion:</b> {data.clusters.map(c => c.count + " queued visits in " + c.state + " (" + c.applications.join(", ") + ")").join("; ")} - one committee tour can cover each cluster.</div>}
    <Card pad={false}><Table rows={rows} empty="No visits in this state" cols={[
      { h: "App ID", r: r => <span className="font-mono text-[12px]">{r.app_no}</span> },
      { h: "Institution", r: r => <span>{r.institution_name}<div className="text-[11px] text-slate-400">{r.state} · {fmt.title(r.institution_type)} · {fmt.title(r.category)}</div></span> },
      { h: tab === "QUEUED" ? "Schedule by" : tab === "SCHEDULED" ? "Visit date" : "Report", r: r => tab === "QUEUED" ? <span>{fmt.date(r.due_by)} <Chip value={r.overdue ? "OVERDUE" : r.days_to_due <= 3 ? "DUE_SOON" : "ON_TRACK"} label={r.overdue ? "Overdue " + (-r.days_to_due) + " d" : "in " + r.days_to_due + " d"} /></span> : tab === "SCHEDULED" ? fmt.date(r.scheduled_on) : fmt.dt(r.report_submitted_at) + " · " + fmt.title(r.outcome) },
      { h: "Committee", r: r => (r.members || []).map(m => m.name).join(", ") || <span className="text-slate-300">not constituted</span> },
      { h: "", r: r => <div className="flex gap-1">{tab === "QUEUED" && canSchedule && <Btn small tone="primary" onClick={() => setSched(r)}>Schedule</Btn>}{tab === "SCHEDULED" && canComplete && <Btn small tone="ok" onClick={() => setDone(r)}>Submit report</Btn>}</div> },
    ]} /></Card>
    {sched && <ScheduleModal v={sched} experts={data.experts} min={data.min_members} onClose={() => setSched(null)} onDone={() => { setSched(null); reload(); toast.show("EVC scheduled; committee and institution notified"); }} onErr={m => toast.show(m, "err")} />}
    {done && <Modal title={"EVC report - " + done.app_no} onClose={() => setDone(null)}><CompleteForm v={done} onDone={() => { setDone(null); reload(); toast.show("EVC report recorded"); }} onErr={m => toast.show(m, "err")} /></Modal>}
  </div>);
}
function ScheduleModal({ v, experts, min, onClose, onDone, onErr }) {
  const [date, setDate] = useState(""); const [members, setMembers] = useState([]); const [remarks, setRemarks] = useState("");
  const toggle = n => setMembers(m => m.includes(n) ? m.filter(x => x !== n) : m.concat(n));
  return (<Modal title={"Schedule EVC - " + v.app_no + " · " + v.institution_name} onClose={onClose}>
    <Field label="Visit date"><input type="date" className={inputCls} value={date} onChange={e => setDate(e.target.value)} /></Field>
    <Field label={"Committee members (minimum " + min + ")"} hint="Conflict-of-interest guard: experts from the institution's own State are blocked by the server.">
      <div className="grid grid-cols-2 gap-1">{experts.map(e => <label key={e.name} className={"flex items-center gap-2 rounded-md border px-2 py-1.5 text-[12px] " + (e.state === v.state ? "border-red-200 bg-red-50 text-red-700" : "border-slate-200")}><input type="checkbox" checked={members.includes(e.name)} onChange={() => toggle(e.name)} /><span>{e.name}<div className="text-[10px] text-slate-500">{e.expertise} · {e.state}{e.state === v.state ? " · same State" : ""}</div></span></label>)}</div></Field>
    <Field label="Remarks"><input className={inputCls} value={remarks} onChange={e => setRemarks(e.target.value)} /></Field>
    <Btn tone="primary" disabled={!date || members.length < min} onClick={async () => { try { await api.post("/evc/" + v.id + "/schedule", { scheduled_on: date, members, remarks }); onDone(); } catch (e) { onErr(e.message); } }}>Confirm schedule</Btn>
  </Modal>);
}
function CompleteForm({ v, onDone, onErr }) {
  const [outcome, setOutcome] = useState("RECOMMENDED"); const [remarks, setRemarks] = useState("");
  return (<div><Field label="Committee outcome"><Sel value={outcome} onChange={setOutcome} options={[["RECOMMENDED", "Recommended"], ["DEFICIENCIES", "Deficiencies observed"], ["NOT_RECOMMENDED", "Not recommended"]]} /></Field>
    <Field label="Observations"><textarea rows="3" className={inputCls} value={remarks} onChange={e => setRemarks(e.target.value)} /></Field>
    <Btn tone="ok" onClick={async () => { try { await api.post("/evc/" + v.id + "/complete", { outcome, remarks }); onDone(); } catch (e) { onErr(e.message); } }}>Submit report</Btn></div>);
}
