import { Alert, Badge, Button, Card, Grid, Group, Loader, Paper, Progress, Stack, Text, Title } from "@mantine/core";
import { IconPlayerPlay } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { endpoints } from "../api/endpoints";
import type { Task } from "../api/types";
import { PriorityBadge, ProvenanceBadges } from "../components/TaskBadges";
import { TimerPanel } from "../components/TimerPanel";
import { useAppMutation, useCurrentSession } from "../hooks/useFocus";
import { formatDate, formatDateTime, formatMinutes } from "../lib/format";

function TaskRow({ task, canStart }: { task: Task; canStart: boolean }) {
  const start = useAppMutation(() => endpoints.startFocus({ task_id: task.id, type: "work" }));
  const remaining = task.estimated_minutes ? Math.max(0, task.estimated_minutes - task.actual_minutes) : null;
  return (
    <Group justify="space-between" wrap="nowrap" py={6}>
      <Stack gap={2} style={{ minWidth: 0 }}>
        <Group gap={6}>
          <Text fw={500} truncate>{task.title}</Text>
          <PriorityBadge priority={task.priority} />
          {task.status === "in_progress" && <Badge size="sm" color="teal" variant="light">in progress</Badge>}
        </Group>
        <Group gap={8}>
          {task.deadline && <Text size="xs" c="dimmed">due {formatDateTime(task.deadline)}</Text>}
          {remaining !== null && <Text size="xs" c="dimmed">{formatMinutes(remaining)} left of {formatMinutes(task.estimated_minutes)}</Text>}
          <ProvenanceBadges task={task} />
        </Group>
      </Stack>
      {canStart && (
        <Button size="xs" variant="light" leftSection={<IconPlayerPlay size={14} />} onClick={() => start.mutate(undefined)}
          loading={start.isPending}>
          Start
        </Button>
      )}
    </Group>
  );
}

export function DashboardPage() {
  const today = useQuery({ queryKey: ["dashboard"], queryFn: endpoints.dashboard, refetchInterval: 60_000 });
  const { session, active } = useCurrentSession();
  if (today.isLoading) return <Loader />;
  if (today.error) return <Alert color="red" title="Cannot reach the Time OS API">{String(today.error)}</Alert>;
  const d = today.data!;
  const liveWorkMin = session?.type === "work" ? active / 60 : 0;
  const finishedMin = d.focused_minutes - (d.current_session?.type === "work" ? d.current_session.active_so_far_s / 60 : 0);
  const focused = finishedMin + liveWorkMin;
  const pct = d.planned_minutes ? Math.min(100, (focused / d.planned_minutes) * 100) : 0;
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Today</Title>
        <Text c="dimmed">{formatDate(d.date)} · {d.timezone}</Text>
      </Group>
      <Grid>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Paper withBorder p="md">
            <Group justify="space-between">
              <Text>Focused <b>{formatMinutes(focused)}</b></Text>
              <Text>Planned <b>{formatMinutes(d.planned_minutes)}</b></Text>
            </Group>
            <Progress value={pct} mt="sm" size="lg" />
            <Group mt="xs" gap="lg">
              <Text size="sm" c="dimmed">{d.sessions_today} sessions logged</Text>
              <Text size="sm" c="dimmed">Rest {formatMinutes(d.rest_minutes)}</Text>
            </Group>
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          {session ? <TimerPanel session={session} active={active} /> : (
            <Card withBorder p="md" h="100%">
              <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Current</Text>
              <Text mt="xs">No session running.</Text>
              <Button component={Link} to="/focus" mt="sm" variant="light">Open focus timer</Button>
            </Card>
          )}
        </Grid.Col>
      </Grid>
      {(d.inbox_count > 0 || d.pending_approval_count > 0) && (
        <Alert variant="light" color="violet">
          {d.inbox_count > 0 && <>{d.inbox_count} task(s) in your inbox to organise. </>}
          {d.pending_approval_count > 0 && <>{d.pending_approval_count} AI proposal(s) waiting for your approval. </>}
          <Link to="/tasks">Review</Link>
        </Alert>
      )}
      <Grid>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Paper withBorder p="md">
            <Title order={4}>Next</Title>
            <Text size="xs" c="dimmed" mb="xs">Overdue first, then in progress, deadline, priority and importance.</Text>
            {d.next_tasks.length === 0 ? <Text c="dimmed">Nothing planned for today.</Text>
              : d.next_tasks.map((t) => <TaskRow key={t.id} task={t} canStart={!session} />)}
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Stack>
            <Paper withBorder p="md">
              <Title order={5}>Due today</Title>
              {d.due_today.length === 0 ? <Text c="dimmed" size="sm">Nothing due today.</Text>
                : d.due_today.map((t) => <TaskRow key={t.id} task={t} canStart={false} />)}
            </Paper>
            {d.overdue.length > 0 && (
              <Paper withBorder p="md" style={{ borderColor: "var(--mantine-color-red-5)" }}>
                <Title order={5} c="red">Overdue</Title>
                {d.overdue.map((t) => <TaskRow key={t.id} task={t} canStart={false} />)}
              </Paper>
            )}
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
