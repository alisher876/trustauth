import { useEffect, useState } from "react";

type Health = { status: string; database: string };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Call the backend once when the page loads.
  useEffect(() => {
    fetch("/api/health")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<Health>;
      })
      .then(setHealth)
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem" }}>
      <h1>TrustAuth</h1>
      {error && <p style={{ color: "crimson" }}>Backend not reachable ({error})</p>}
      {!error && !health && <p>Checking backend…</p>}
      {health && (
        <>
          <p style={{ color: "green" }}>Backend connected</p>
          <p>Database: {health.database}</p>
        </>
      )}
    </main>
  );
}
