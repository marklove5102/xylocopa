import TaskRow from "../../components/cards/TaskRow";

export default function PlanningView({ tasks, loading, selecting, selected, onToggle, expandedTaskId, onExpandTask, onRefresh }) {
  const sorted = [...tasks].sort((a, b) => {
    if (b.priority !== a.priority) return b.priority - a.priority;
    return new Date(a.created_at) - new Date(b.created_at);
  });

  if (!loading && sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-faint">
        <svg className="w-10 h-10 mb-2" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25z" />
        </svg>
        <p className="text-sm font-medium">No tasks in planning</p>
        <p className="text-xs mt-1">Move tasks from Inbox to start planning</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-divider">
      {sorted.map((task) => (
        <TaskRow
          key={task.id}
          task={task}
          selecting={selecting}
          selected={selected.has(task.id)}
          onToggle={onToggle}
          expanded={expandedTaskId === task.id}
          onExpand={onExpandTask}
          onRefresh={onRefresh}
        />
      ))}
    </div>
  );
}
