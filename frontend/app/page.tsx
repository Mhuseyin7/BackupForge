const cards = [
  ["Last successful backup", "No verified artifacts yet"],
  ["Failed jobs", "0"],
  ["Unverified backups", "0"],
  ["Storage usage", "—"]
];

export default function Dashboard() {
  return <main className="mx-auto max-w-6xl p-8">
    <header className="mb-10 flex items-center justify-between">
      <div><p className="text-sm text-cyan-300">BACKUPFORGE</p><h1 className="text-3xl font-semibold">Backup verification dashboard</h1></div>
      <button className="rounded bg-cyan-400 px-4 py-2 font-semibold text-slate-950">Create job</button>
    </header>
    <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map(([label, value]) => <article key={label} className="rounded-lg border border-slate-700 bg-slate-900 p-5"><p className="text-sm text-slate-400">{label}</p><p className="mt-3 text-xl">{value}</p></article>)}
    </section>
    <section className="mt-8 rounded-lg border border-slate-700 bg-slate-900 p-6">
      <h2 className="text-xl font-medium">Verification-first operation</h2>
      <p className="mt-2 max-w-2xl text-slate-400">A run is only successful after its encrypted artifact is uploaded and checksum-verified from its configured destination.</p>
      <nav className="mt-6 flex flex-wrap gap-3 text-cyan-300">{["Jobs", "Backups", "Restores", "Verification", "Storage", "Notifications", "Audit", "Settings"].map(item => <a key={item} href="#">{item}</a>)}</nav>
    </section>
  </main>;
}
