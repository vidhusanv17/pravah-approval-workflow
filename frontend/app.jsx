/* App shell: login, role-based navigation, demo controls, hash routing. */

const NAV = {
  officer: [["overview", "Overview"], ["applications", "Applications"], ["evc", "EVC Scheduling"], ["undertakings", "Undertakings & Compliance"], ["documents", "Document Validity"], ["alerts", "Alerts & Escalations"], ["outbox", "Notification Outbox"], ["reports", "Reports"], ["institutions", "Institutions"], ["audit", "Audit Trail"], ["rules", "Rules"]],
  evc: [["overview", "Overview"], ["evc", "EVC Visits"], ["applications", "Applications"], ["audit", "Audit Trail"]],
  institution: [["home", "My Dashboard"], ["my-applications", "My Applications"], ["submit", "Submit Application"], ["undertakings", "Undertakings"], ["documents", "Documents"], ["alerts", "Alerts & Reminders"], ["outbox", "Messages Received"]],
};

function Login({ onLogin }) {
  const { data } = useApi("/auth/demo-users");
  const [u, setU] = useState(""); const [p, setP] = useState("demo123"); const [err, setErr] = useState(null);
  const login = async (username, password) => { try { const r = await api.post("/auth/login", { username, password }); localStorage.setItem("pravah_token", r.token); localStorage.setItem("pravah_user", JSON.stringify(r.user)); onLogin(r.user); } catch (e) { setErr(e.message); } };
  const groups = data ? [["AICTE officials", data.filter(x => ["REGIONAL_OFFICER", "BUREAU_OFFICER", "MEMBER_SECRETARY"].includes(x.role))], ["Committees & admin", data.filter(x => ["EVC_MEMBER", "ADMIN"].includes(x.role))], ["Institutions", data.filter(x => x.role === "INSTITUTION")]] : [];
  return (<div className="min-h-screen flex"><div className="hidden lg:flex w-[42%] bg-navy-800 text-white flex-col justify-between p-10">
    <div><div className="text-3xl font-extrabold tracking-[.15em]">PRAVAH</div><div className="text-blue-200 text-[13px] mt-1">Integrated AICTE Approval Workflow Automation, Compliance Monitoring & Alert Management</div>
      <ul className="mt-10 space-y-3 text-[13px] text-blue-100">{["Auto-routing through APH-prescribed stages - Scrutiny, Re-scrutiny, EVC, SAC/SHC", "Stage SLAs, pendency ageing and a 3-level escalation ladder", "EVC queueing, geo-clustered scheduling, conflict-of-interest guard", "Undertakings, lease & document validity tracked as dated obligations", "Email / SMS / WhatsApp reminders; digest for routine, instant for critical", "Hash-chained audit trail and QR-verified approval letters", "Compliance score opens a Green Channel - statutory stages never skipped"].map((t, i) => <li key={i} className="flex gap-2"><span className="text-blue-300">{"\u25B8"}</span>{t}</li>)}</ul></div>
    <div className="text-[11px] text-blue-300">Smart India Hackathon 2026 · PS SIH26262 · prototype with synthetic data. Automated alerts and routing support the approval process; statutory scrutiny, inspections and decisions remain with competent AICTE authorities.</div></div>
    <div className="flex-1 flex items-center justify-center p-8"><div className="w-full max-w-lg">
      <h1 className="text-xl font-semibold text-slate-900">Sign in</h1><div className="text-[12px] text-slate-500 mb-4">Role-based access (JWT + RBAC). Pick a demo account or enter credentials.</div>
      <div className="flex gap-2 mb-2"><input className={inputCls} placeholder="username" value={u} onChange={e => setU(e.target.value)} /><input className={inputCls} type="password" value={p} onChange={e => setP(e.target.value)} /><Btn tone="primary" onClick={() => login(u, p)}>Login</Btn></div>
      <ErrorBox error={err} />
      {groups.map(([g, list]) => <div key={g} className="mt-4"><div className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">{g}</div><div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">{list.map(x => <button key={x.username} onClick={() => login(x.username, x.password)} className="text-left rounded-lg border border-slate-200 bg-white px-3 py-2 hover:border-blue-400 hover:bg-blue-50 transition"><div className="text-[13px] font-medium text-slate-800">{x.name}</div><div className="text-[11px] text-slate-500">{x.designation}</div><div className="text-[10px] text-slate-400 font-mono">{x.username} / {x.password}</div></button>)}</div></div>)}
    </div></div></div>);
}

function DemoBar({ user, onChanged }) {
  const [h, setH] = useState(null); const [busy, setBusy] = useState(false);
  const refresh = () => api.get("/health").then(setH).catch(() => {});
  useEffect(() => { refresh(); }, []);
  const run = async (fn) => { setBusy(true); try { await fn(); await refresh(); onChanged(); } finally { setBusy(false); } };
  return (<div className="flex items-center gap-2 text-[11px] text-slate-600">
    <span className="rounded-md bg-amber-50 border border-amber-200 px-2 py-1">Demo clock: <b>{h ? fmt.date(h.now) : "..."}</b>{h && h.clock_offset_days ? <span className="text-amber-700"> (+{h.clock_offset_days} d)</span> : ""}</span>
    <Btn small disabled={busy} title="Move time forward to see reminders, overdue states and escalations fire" onClick={() => run(() => api.post("/demo/clock", { days: 7 }))}>+7 days</Btn>
    <Btn small disabled={busy} onClick={() => run(() => api.post("/jobs/run"))}>Run monitors now</Btn>
    {user.role === "ADMIN" && <Btn small tone="danger" disabled={busy} onClick={() => run(() => api.post("/demo/reset"))}>Reset demo data</Btn>}
  </div>);
}

function App() {
  const [user, setUser] = useState(() => {
    if (new URLSearchParams(window.location.search).get("demo")) { localStorage.removeItem("pravah_token"); localStorage.removeItem("pravah_user"); return null; }
    try { return api.token() ? JSON.parse(localStorage.getItem("pravah_user")) : null; } catch (e) { return null; }
  });
  const { parts, go } = useHash();
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => { const f = () => setUser(null); window.addEventListener("pravah-logout", f); return () => window.removeEventListener("pravah-logout", f); }, []);
  // Deep link for demos/screenshots: /?demo=ro.south#/overview signs in as that demo account.
  useEffect(() => {
    const demo = new URLSearchParams(window.location.search).get("demo");
    if (demo) { api.post("/auth/login", { username: demo, password: "demo123" }).then(r => { localStorage.setItem("pravah_token", r.token); localStorage.setItem("pravah_user", JSON.stringify(r.user)); setUser(r.user); }).catch(() => {}); }
  }, []);
  const pathCode = window.location.pathname.startsWith("/verify/") ? window.location.pathname.split("/")[2] : null;
  if (parts[0] === "verify" || pathCode) return <VerifyPage code={parts[1] || pathCode} />;
  if (!user) return <Login onLogin={u => { setUser(u); go(u.role === "INSTITUTION" ? "home" : "overview"); }} />;
  const navKey = user.role === "INSTITUTION" ? "institution" : user.role === "EVC_MEMBER" ? "evc" : "officer";
  const nav = NAV[navKey];
  const page = parts[0] || nav[0][0];
  const sub = parts[1];
  const bump = () => setRefreshKey(k => k + 1);
  const logout = () => { localStorage.removeItem("pravah_token"); localStorage.removeItem("pravah_user"); setUser(null); go(""); };
  let body;
  switch (page) {
    case "overview": body = <Overview user={user} go={go} refreshKey={refreshKey} />; break;
    case "applications": body = <Applications user={user} go={go} selectedId={sub && sub !== "overdue" ? sub : null} filter={sub === "overdue" ? "overdue" : null} refreshKey={refreshKey} />; break;
    case "evc": body = <EVC user={user} refreshKey={refreshKey} />; break;
    case "undertakings": body = <Undertakings user={user} refreshKey={refreshKey} />; break;
    case "documents": body = <Documents user={user} refreshKey={refreshKey} />; break;
    case "alerts": body = <Alerts user={user} refreshKey={refreshKey} />; break;
    case "outbox": body = <Outbox refreshKey={refreshKey} />; break;
    case "reports": body = <Reports user={user} />; break;
    case "audit": body = <Audit refreshKey={refreshKey} />; break;
    case "rules": body = <Rules user={user} />; break;
    case "institutions": body = <Institutions go={go} selectedId={sub} refreshKey={refreshKey} />; break;
    case "home": body = <InstitutionHome user={user} go={go} refreshKey={refreshKey} />; break;
    case "submit": body = <SubmitApplication user={user} go={go} />; break;
    case "my-applications": body = <MyApplications user={user} go={go} selectedId={sub} refreshKey={refreshKey} />; break;
    default: body = <Empty text="Page not found" />;
  }
  return (<div className="min-h-screen flex">
    <aside className="w-[230px] shrink-0 bg-navy-800 text-white flex flex-col">
      <div className="px-5 pt-5 pb-4"><div className="text-[22px] font-extrabold tracking-[.12em]">PRAVAH</div><div className="text-[10px] text-blue-200 leading-tight">AICTE Approval Workflow &amp; Compliance</div></div>
      <nav className="px-3 flex-1">{nav.map(([k, l]) => <a key={k} href={"#/" + k} className={"block rounded-md px-3 py-2 text-[13px] mb-0.5 " + (page === k ? "bg-navy-700 font-semibold" : "text-blue-100 hover:bg-navy-900/60")}>{l}</a>)}</nav>
      <div className="px-5 py-4 text-[10px] text-blue-200 border-t border-navy-700">SIH 2026 · PS 26262 · synthetic data<br />Decision support only - statutory decisions stay with AICTE.</div>
    </aside>
    <main className="flex-1 min-w-0">
      <header className="bg-white border-b border-slate-200 px-5 py-2.5 flex items-center justify-between gap-3 sticky top-0 z-40">
        <DemoBar user={user} onChanged={bump} />
        <div className="flex items-center gap-3 text-[12px] text-slate-600"><div className="text-right"><div className="font-semibold text-slate-800">{user.name}</div><div className="text-[11px]">{user.designation} · {ROLE_LABELS[user.role]}{user.region_label ? " · " + user.region_label : ""}</div></div><Btn small onClick={logout}>Sign out</Btn></div>
      </header>
      <div className="p-5">{body}</div>
    </main></div>);
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
