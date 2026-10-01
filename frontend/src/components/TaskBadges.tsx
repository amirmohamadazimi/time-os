import { Badge, Group, Tooltip } from "@mantine/core";
import type { Task } from "../api/types";

const STATUS_COLOR: Record<string, string> = {
  inbox: "gray", planned: "blue", in_progress: "teal", blocked: "orange", completed: "green", cancelled: "dark",
};
const PRIORITY_COLOR: Record<string, string> = { low: "gray", medium: "blue", high: "orange", critical: "red" };

export function StatusBadge({ status }: { status: Task["status"] }) {
  return <Badge color={STATUS_COLOR[status]} variant="light">{status.replace("_", " ")}</Badge>;
}

export function PriorityBadge({ priority }: { priority: Task["priority"] }) {
  return <Badge color={PRIORITY_COLOR[priority]} variant="dot">{priority}</Badge>;
}

/** Makes provenance obvious: user-created, AI-suggested, recurring or imported. */
export function ProvenanceBadges({ task }: { task: Task }) {
  return (
    <Group gap={4}>
      {task.pending_approval && <Badge color="violet" variant="filled" size="sm">AI proposal · needs approval</Badge>}
      {task.source === "ai" && !task.pending_approval && <Badge color="violet" variant="light" size="sm">AI-suggested</Badge>}
      {task.source === "recurrence" && <Badge color="cyan" variant="light" size="sm">recurring</Badge>}
      {task.is_template && <Badge color="cyan" variant="outline" size="sm">template · {task.recurrence_rule}</Badge>}
      {task.source === "import" && <Badge color="gray" variant="light" size="sm">imported</Badge>}
      {task.blocked_by.length > 0 && (
        <Tooltip label={`Waiting on ${task.blocked_by.length} unfinished prerequisite(s)`}>
          <Badge color="orange" variant="outline" size="sm">blocked by dependency</Badge>
        </Tooltip>
      )}
    </Group>
  );
}
