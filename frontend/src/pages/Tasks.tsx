import {
  ActionIcon, Alert, Badge, Button, Group, Loader, Menu, MultiSelect, Paper, SegmentedControl, Select, Stack, Table,
  Text, Textarea, TextInput, Title, Tooltip,
} from "@mantine/core";
import {
  IconCheck, IconDots, IconPencil, IconPlayerPlay, IconPlus, IconSearch, IconThumbUp, IconTrash,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { endpoints } from "../api/endpoints";
import type { Task, TaskStatus } from "../api/types";
import { PriorityBadge, ProvenanceBadges, StatusBadge } from "../components/TaskBadges";
import { TaskForm } from "../components/TaskForm";
import { useAppMutation, useCurrentSession } from "../hooks/useFocus";
import { formatDate, formatDateTime, formatMinutes } from "../lib/format";
import { notifyOk } from "../lib/notify";

const VIEWS: Record<string, { label: string; status?: TaskStatus[]; pending_approval?: boolean; templates?: boolean }> = {
  open: { label: "Open", status: ["inbox", "planned", "in_progress", "blocked"] },
  inbox: { label: "Inbox", status: ["inbox"] },
  approval: { label: "Needs approval", pending_approval: true },
  recurring: { label: "Recurring", templates: true },
  done: { label: "Done", status: ["completed", "cancelled"] },
};

/** Paste or type several lines; each becomes an inbox task to organise later. */
function QuickCapture() {
  const [text, setText] = useState("");
  const capture = useAppMutation(endpoints.captureInbox, (created) => {
    notifyOk(`${created.length} task(s) added to the inbox`);
    setText("");
  });
  return (
    <Paper withBorder p="md">
      <Group align="end">
        <Textarea style={{ flex: 1 }} label="Quick capture" autosize minRows={1} maxRows={6}
          placeholder="One task per line. Organise them later from the Inbox."
          value={text} onChange={(e) => setText(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && text.trim()) capture.mutate(text);
          }} />
        <Button onClick={() => capture.mutate(text)} disabled={!text.trim()} loading={capture.isPending}>
          Add to inbox
        </Button>
      </Group>
    </Paper>
  );
}

function TaskActions({ task, onEdit, canStart }: { task: Task; onEdit: () => void; canStart: boolean }) {
  const start = useAppMutation(() => endpoints.startFocus({ task_id: task.id, type: "work" }));
  const complete = useAppMutation(() => endpoints.completeTask(task.id), () => notifyOk("Task completed"));
  const approve = useAppMutation(() => endpoints.approveTask(task.id), () => notifyOk("Proposal approved"));
  const remove = useAppMutation(() => endpoints.deleteTask(task.id), () => notifyOk("Task deleted"));
  const open = !["completed", "cancelled"].includes(task.status) && !task.is_template;
  return (
    <Group gap={4} wrap="nowrap" justify="flex-end">
      {task.pending_approval && (
        <Tooltip label="Approve AI proposal">
          <ActionIcon color="violet" variant="light" onClick={() => approve.mutate(undefined)} loading={approve.isPending}>
            <IconThumbUp size={16} />
          </ActionIcon>
        </Tooltip>
      )}
      {open && canStart && !task.pending_approval && (
        <Tooltip label={task.blocked_by.length ? "Waiting on a strict prerequisite" : "Start focus session"}>
          <ActionIcon variant="light" disabled={task.blocked_by.length > 0} onClick={() => start.mutate(undefined)}
            loading={start.isPending}>
            <IconPlayerPlay size={16} />
          </ActionIcon>
        </Tooltip>
      )}
      {open && (
        <Tooltip label="Mark done">
          <ActionIcon color="teal" variant="light" onClick={() => complete.mutate(undefined)} loading={complete.isPending}>
            <IconCheck size={16} />
          </ActionIcon>
        </Tooltip>
      )}
      <Menu position="bottom-end" withinPortal>
        <Menu.Target>
          <ActionIcon variant="subtle" color="gray"><IconDots size={16} /></ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item leftSection={<IconPencil size={14} />} onClick={onEdit}>Edit</Menu.Item>
          <Menu.Item color="red" leftSection={<IconTrash size={14} />}
            onClick={() => {
              if (window.confirm(`Delete "${task.title}"? Its focus history is kept.`)) remove.mutate(undefined);
            }}>
            Delete
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
}

export function TasksPage() {
  const [view, setView] = useState("open");
  const [search, setSearch] = useState("");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [priorities, setPriorities] = useState<string[]>([]);
  const [editing, setEditing] = useState<Task | null | undefined>(undefined);
  const { session } = useCurrentSession();
  const v = VIEWS[view];
  const tasks = useQuery({
    queryKey: ["tasks", view, search, projectId],
    queryFn: () => endpoints.tasks({
      status: v.status, pending_approval: v.pending_approval, include_templates: v.templates,
      q: search.trim() || undefined, project_id: projectId ?? undefined,
    }),
  });
  const projects = useQuery({ queryKey: ["projects", "all"], queryFn: () => endpoints.projects() });
  const projectName = useMemo(
    () => Object.fromEntries((projects.data ?? []).map((p) => [p.id, p.name])), [projects.data],
  );
  const rows = (tasks.data ?? [])
    .filter((t) => (view === "recurring" ? t.is_template : true))
    .filter((t) => !priorities.length || priorities.includes(t.priority));

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Tasks</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing(null)}>New task</Button>
      </Group>
      <QuickCapture />
      <Group>
        <SegmentedControl value={view} onChange={setView}
          data={Object.entries(VIEWS).map(([value, { label }]) => ({ value, label }))} />
        <TextInput leftSection={<IconSearch size={14} />} placeholder="Search title, notes" value={search}
          onChange={(e) => setSearch(e.currentTarget.value)} />
        <Select placeholder="Any project" clearable value={projectId} onChange={setProjectId}
          data={(projects.data ?? []).map((p) => ({ value: p.id, label: p.name }))} />
        <MultiSelect placeholder="Any priority" value={priorities} onChange={setPriorities} clearable
          data={["critical", "high", "medium", "low"]} w={220} />
      </Group>
      {tasks.error && <Alert color="red">{String(tasks.error)}</Alert>}
      {tasks.isLoading ? <Loader /> : rows.length === 0 ? (
        <Text c="dimmed">No tasks here.</Text>
      ) : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={900}>
            <Table verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Task</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Project</Table.Th>
                  <Table.Th>Planned / due</Table.Th>
                  <Table.Th>Estimate · actual</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((t) => (
                  <Table.Tr key={t.id}>
                    <Table.Td>
                      <Stack gap={4}>
                        <Group gap={6}>
                          <Text fw={500}>{t.title}</Text>
                          <PriorityBadge priority={t.priority} />
                        </Group>
                        <Group gap={4}>
                          {t.category && <Badge size="sm" variant="outline" color="gray">{t.category}</Badge>}
                          {t.tags.map((tag) => <Badge key={tag} size="sm" variant="light" color="gray">#{tag}</Badge>)}
                          <ProvenanceBadges task={t} />
                        </Group>
                      </Stack>
                    </Table.Td>
                    <Table.Td><StatusBadge status={t.status} /></Table.Td>
                    <Table.Td>{t.project_id ? projectName[t.project_id] ?? "–" : "–"}</Table.Td>
                    <Table.Td>
                      <Text size="sm">{t.planned_date ? formatDate(t.planned_date) : "–"}</Text>
                      {t.deadline && (
                        <Text size="xs" c={new Date(t.deadline) < new Date() && t.status !== "completed" ? "red" : "dimmed"}>
                          due {formatDateTime(t.deadline)}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">
                        {formatMinutes(t.estimated_minutes)} · {formatMinutes(t.actual_minutes)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <TaskActions task={t} onEdit={() => setEditing(t)} canStart={!session} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      <TaskForm opened={editing !== undefined} task={editing} onClose={() => setEditing(undefined)} />
    </Stack>
  );
}
