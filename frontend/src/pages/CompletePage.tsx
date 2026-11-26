export function CompletePage({ answeredCount }: { answeredCount?: number }) {
  return (
    <main className="page">
      <section className="card hero" aria-labelledby="complete-heading">
        <div className="check" aria-hidden="true">✓</div>
        <h1 id="complete-heading">Interview submitted</h1>
        <p className="lead">
          Thank you! {answeredCount ? `${answeredCount} answers were` : "Your answers were"} received. The hiring team
          will review them. You can now close this page.
        </p>
      </section>
    </main>
  );
}
