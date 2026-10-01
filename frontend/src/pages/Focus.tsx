import {
  Alert, Badge, Button, Grid, Group, Loader, NumberInput, Paper, SegmentedControl, Select, Stack, TagsInput, Text,
  Textarea, Title,
} from "@mantine/core";
import { IconArrowsExchange, IconPlayerPlay, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import { endpoints } from "../api/endpoints";
import type { LiveSession, Task } from "../api/types";
import { TimerPanel } from "../components/TimerPanel";
import { useAppMutation, useCurrentSession } from "../hooks/useFocus";
import { formatMinutes, formatTime, isoDate } from "../lib/format";
import { notifyOk } from "../lib/notify";

function useWorkableTasks() {
  return useQuery({
    queryKey: ["tasks", "workable"],
    queryFn: () => endpoints.tasks({ status: ["planned", "in_progress", "inbox", "blocked"], pending_approval: false }),
    select: (tasks: Task[]) => tasks.filter((t) => t.blocked_by.length === 0),
  });
}

const taskOptions = (tasks: Task[] = []) =>
  tasks.map((t) => ({
    value: t.id,
    label: t.estimated_minutes ? `${t.title} (${formatMinutes(t.estimated_minutes - t.actual_minutes)} left)` : t.title,
  }));

function StartForm() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: endpoints.settings });
  const tasks = useWorkableTasks();
  const [type, setType] = useState<"work" | "rest">("work");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [minutes, setMinutes] = useState<number | string>(25);
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  useEffect(() => {
    if (settings.data) setMinutes(type === "work" ? settings.data.focus.work_minutes : settings.data.focus.break_minutes);
  }, [type, settings.data]);
  const start = useAppMutation(endpoints.startFocus);
  return (
    <Paper withBorder p="xl">
      <Stack>
        <Title order={3}>Start a session</Title>
        <SegmentedControl value={type} onChange={(v) => setType(v as "work" | "rest")}
          data={[{ value: "work", label: "Work" }, { value: "rest", label: "Break" }]} />
        {type === "work" && (
          <Select label="Task" placeholder="Unassigned work session" clearable searchable value={taskId}
            onChange={setTaskId} data={taskOptions(tasks.data)}
            description="Tasks waiting on a strict prerequisite or on approval are not listed." />
        )}
        <NumberInput label="Planned duration (minutes)" min={1} max={480} value={minutes} onChange={setMinutes}
          description="Leave empty for an open-ended session." />
        <Textarea label="Note" autosize minRows={1} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
        <TagsInput label="Tags" value={tags} onChange={setTags} />
        <Button size="md" leftSection={<IconPlayerPlay size={18} />} loading={start.isPending}
          onClick={() => start.mutate({
            type,
            task_id: type === "work" ? taskId : null,
            planned_duration_s: minutes === "" ? null : Number(minutes) * 60,
            notes: notes.trim() || null,
            tags,
          })}>
          Start {type === "work" ? "focus" : "break"}
        </Button>
      </Stack>
    </Paper>
  );
}

function LiveControls({ session }: { session: LiveSession }) {
  const tasks = useWorkableTasks();
  const [target, setTarget] = useState<string | null>(null);
  const [notes, setNotes] = useState(session.notes ?? "");
  const [tags, setTags] = useState<string[]>(session.tags);
  useEffect(() => {
    setNotes(session.notes ?? "");
    setTags(session.tags);
  }, [session.id, session.notes, session.tags]);
  const switchTask = useAppMutation(endpoints.switchFocus, () => {
    notifyOk("Switched task; the previous session was logged as switched");
    setTarget(null);
  });
  const annotate = useAppMutation(endpoints.annotateFocus, () => notifyOk("Saved"));
  const discard = useAppMutation(endpoints.discardFocus, () => notifyOk("Session discarded"));
  return (
    <Stack>
      {session.type === "work" && (
        <Paper withBorder p="md">
          <Text fw={600} mb="xs">Switch task</Text>
          <Group align="end">
            <Select style={{ flex: 1 }} placeholder="Pick the task you're moving to" searchable value={target}
              onChange={setTarget} data={taskOptions(tasks.data?.filter((t) => t.id !== session.task_id))} />
            <Button leftSection={<IconArrowsExchange size={16} />} disabled={!target} loading={switchTask.isPending}
              onClick={() => target && switchTask.mutate({ task_id: target, planned_duration_s: session.planned_duration_s })}>
              Switch
            </Button>
          </Group>
        </Paper>
      )}
      <Paper withBorder p="md">
        <Stack gap="xs">
          <Textarea label="Note" autosize minRows={2} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
          <TagsInput label="Tags" value={tags} onChange={setTags} />
          <Group justify="space-between">
            <Button variant="subtle" color="red" leftSection={<IconTrash size={14} />}
              onClick={() => {
                if (window.confirm("Discard this session? It will not be logged.")) discard.mutate(undefined);
              }}>
              Discard
            </Button>
            <Button variant="light" loading={annotate.isPending}
              onClick={() => annotate.mutate({ notes: notes.trim() || null, tags })}>
              Save note
            </Button>
          </Group>
        </Stack>
      </Paper>
    </Stack>
  );
}

function TodaySessions() {
  const today = isoDate(dayjs());
  const sessions = useQuery({
    queryKey: ["sessions", "today", today],
    queryFn: () => endpoints.sessions({ from: today, to: today, limit: 50 }),
  });
  const items = (sessions.data?.items ?? []).filter((s) => s.state === "finished");
  return (
    <Paper withBorder p="md">
      <Title order={5} mb="xs">Today's sessions</Title>
      {items.length === 0 ? <Text size="sm" c="dimmed">None yet.</Text> : items.map((s) => (
        <Group key={s.id} justify="space-between" py={4} wrap="nowrap">
          <Text size="sm" truncate>
            {formatTime(s.start_time)}–{formatTime(s.end_time)} · {s.task_title_snapshot ?? (s.type === "rest" ? "Break" : "Untitled")}
          </Text>
          <Group gap={4} wrap="nowrap">
            <Text size="sm" fw={500}>{formatMinutes((s.active_duration_s ?? 0) / 60)}</Text>
            {s.end_reason && s.end_reason !== "completed" && <Badge size="xs" variant="light" color="gray">{s.end_reason}</Badge>}
          </Group>
        </Group>
      ))}
    </Paper>
  );
}

export function FocusPage() {
  const { session, active, isLoading } = useCurrentSession();
  if (isLoading) return <Loader />;
  return (
    <Stack>
      <Title order={2}>Focus</Title>
      <Alert variant="light" color="gray">
        The server keeps the timer, so it survives refreshes, closed tabs and other devices.
      </Alert>
      <Grid>
        <Grid.Col span={{ base: 12, md: 7 }}>
          {session ? <TimerPanel session={session} active={active} large /> : <StartForm />}
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Stack>
            {session && <LiveControls session={session} />}
            <TodaySessions />
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
