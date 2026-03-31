const COLORS: Record<string, string> = {
  pdf: 'bg-red-500/20 text-red-400',
  document: 'bg-red-500/20 text-red-400',
  excel: 'bg-green-500/20 text-green-400',
  data: 'bg-green-500/20 text-green-400',
  email: 'bg-blue-500/20 text-blue-400',
  answer: 'bg-blue-500/20 text-blue-400',
  doc_list: 'bg-purple-500/20 text-purple-400',
  email_trace: 'bg-amber-500/20 text-amber-400',
  sql_result: 'bg-green-500/20 text-green-400',
};

export default function Badge({ label }: { label: string }) {
  const color = COLORS[label.toLowerCase()] ?? 'bg-gray-500/20 text-gray-400';
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}
    >
      {label}
    </span>
  );
}
