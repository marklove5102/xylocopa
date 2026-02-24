import useProjects from "../hooks/useProjects";

export default function ProjectSelector({ value, onChange }) {
  const { projects, loading, error } = useProjects();

  if (loading) return <div className="text-sm text-dim">Loading projects...</div>;
  if (error) return <div className="text-sm text-red-400">{error}</div>;

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full min-h-[44px] rounded-lg bg-input border border-edge px-3 py-2 text-heading focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500 transition-colors"
    >
      <option value="">Select a project...</option>
      {projects.map((p) => (
        <option key={p.name} value={p.name}>
          {p.display_name || p.name}
        </option>
      ))}
    </select>
  );
}
