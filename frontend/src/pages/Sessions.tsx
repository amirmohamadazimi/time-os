import {
  ActionIcon, Badge, Button, Group, Loader, Modal, NumberInput, Pagination, Paper, Select, SimpleGrid, Stack, Switch,
  Table, TagsInput, Text, Textarea, TextInput, Title, Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { IconPlus, IconSearch, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useState } from "react";
import { endpoints } from "../api/endpoints";
import type { FocusSession } from "../api/types";
import { useAppMutation } from "../hooks/useFocus";
import { formatDateTime, formatMinutes, formatTime } from "../lib/format";
import { notifyOk } from "../lib/notify";

const PAGE_SIZE = 50;

function LogSessionModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const tasks = useQuery({
    queryKey: ["tasks", "for-log"],
    queryFn: () => endpoints.tasks({ status: ["planned", "in_progress", "inbox", "blocked", "completed"] }),
    enabled: opened,
  });
  const form = useForm({
    initialValues: {
      type: "work", task_id: null as string | null,
      start: dayjs().subtract(30, "minute").format("YYYY-MM-DDTHH:mm"), end: dayjs().format("YYYY-MM-DDTHH:mm"),
      paused_minutes: 0 as number | string, outcome: null as string | null, notes: "", tags: [] as string[],
    },
    validate: {
      end: (end, v) => (dayjs(end).isAfter(dayjs(v.start)) ? null : "End must be after start"),
    },
  });
  const log = useAppMutation(endpoints.logSession, () => {
    notifyOk("Session logged");
    form.reset();
    onClose();
  });
  return (
    <Modal opened={opened} onClose={onClose} title="Log a session manually" size="lg">
      <form onSubmit={form.onSubmit((v) => log.mutate({
        type: v.type,
        task_id: v.type === "work" ? v.task_id : null,
        start_time: dayjs(v.start).toISOString(),
        end_time: dayjs(v.end).toISOString(),
        paused_duration_s: Number(v.paused_minutes || 0) * 60,
        outcome: v.type === "work" ? v.outcome : null,
        notes: v.notes.trim() || null,
        tags: v.tags,
      }))}>
        <Stack>
          <SimpleGrid cols={2}>
            <Select label="Type" data={[{ value: "work", label: "Work" }, { value: "rest", label: "Break" }]}
              allowDeselect={false} {...form.getInputProps("type")} />
            <Select label="Task" clearable searchable disabled={form.values.type !== "work"}
              data={(tasks.data ?? []).map((t) => ({ value: t.id, label: t.title }))} {...form.getInputProps("task_id")} />
            <TextInput label="Start" type="datetime-local" {...form.getInputProps("start")} />
            <TextInput label="End" type="datetime-local" {...form.getInputProps("end")} />
            <NumberInput label="Paused (minutes)" min={0} {...form.getInputProps("paused_minutes")} />
            <Select label="Outcome" clearable disabled={form.values.type !== "work"}
              data={["completed", "partial", "blocked", "abandoned"]} {...form.getInputProps("outcome")} />
          </SimpleGrid>
          <Textarea label="Note" autosize minRows={2} {...form.getInputProps("notes")} />
          <TagsInput label="Tags" {...form.getInputProps("tags")} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={log.isPending}>Log session</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function SessionRow({ s }: { s: FocusSession }) {
  const exclude = useAppMutation(
    (value: boolean) => endpoints.annotateSession(s.id, { exclude_from_stats: value }),
  );
  const remove = useAppMutation(() => endpoints.voidSession(s.id), () => notifyOk("Session deleted"));
  const live = s.state !== "finished";
  return (
    <Table.Tr style={s.exclude_from_stats ? { opacity: 0.6 } : undefined}>
      <Table.Td>
        <Text size="sm">{formatDateTime(s.start_time)}</Text>
        <Text size="xs" c="dimmed">
          to {!s.end_time ? "now" : dayjs(s.end_time).isSame(s.start_time, "day") ? formatTime(s.end_time) : formatDateTime(s.end_time)}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" fw={500}>{s.task_title_snapshot ?? (s.type === "rest" ? "Break" : "Untitled")}</Text>
        {s.notes && <Text size="xs" c="dimmed" lineClamp={2}>{s.notes}</Text>}
        <Group gap={4} mt={2}>
          {s.tags.map((t) => <Badge key={t} size="xs" variant="light" color="gray">#{t}</Badge>)}
        </Group>
      </Table.Td>
      <Table.Td>
        <Badge size="sm" variant="light" color={s.type === "work" ? "indigo" : "cyan"}>{s.type}</Badge>
      </Table.Td>
      <Table.Td>
        <Text size="sm">{live ? s.state : formatMinutes((s.active_duration_s ?? 0) / 60)}</Text>
        {s.paused_duration_s > 0 && <Text size="xs" c="dimmed">+{formatMinutes(s.paused_duration_s / 60)} paused</Text>}
      </Table.Td>
      <Table.Td>
        <Text size="sm">{s.end_reason ?? "–"}</Text>
        {s.outcome && <Text size="xs" c="dimmed">{s.outcome}</Text>}
      </Table.Td>
      <Table.Td>
        <Group gap={4}>
          <Badge size="sm" variant="outline" color="gray">{s.source}</Badge>
          {s.quality_flags.map((f) => (
            <Tooltip key={f} label="Flagged during import">
              <Badge size="sm" color="orange" variant="light">{f.replace(/_/g, " ")}</Badge>
            </Tooltip>
          ))}
        </Group>
      </Table.Td>
      <Table.Td>
        {!live && (
          <Group gap={6} wrap="nowrap" justify="flex-end">
            <Tooltip label="Count this session in analytics">
              <Switch size="xs" checked={!s.exclude_from_stats} onChange={(e) => exclude.mutate(!e.currentTarget.checked)} />
            </Tooltip>
            <ActionIcon variant="subtle" color="red" loading={remove.isPending}
              onClick={() => {
                if (window.confirm("Delete this session? It is hidden from history and analytics (recorded in the audit log).")) {
                  remove.mutate(undefined);
                }
              }}>
              <IconTrash size={16} />
            </ActionIcon>
          </Group>
        )}
      </Table.Td>
    </Table.Tr>
  );
}

export function SessionsPage() {
  const [from, setFrom] = useState(dayjs().subtract(30, "day").format("YYYY-MM-DD"));
  const [to, setTo] = useState(dayjs().format("YYYY-MM-DD"));
  const [type, setType] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [logging, setLogging] = useState(false);
  const filters = { from: from || undefined, to: to || undefined, type: (type ?? undefined) as "work" | "rest" | undefined,
    source: source ?? undefined, q: search.trim() || undefined };
  const sessions = useQuery({
    queryKey: ["sessions", filters, page],
    queryFn: () => endpoints.sessions({ ...filters, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }),
  });
  const total = sessions.data?.total ?? 0;
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(1);
  };
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Sessions</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setLogging(true)}>Log session</Button>
      </Group>
      <Group align="end">
        <TextInput label="From" type="date" value={from} onChange={(e) => reset(setFrom)(e.currentTarget.value)} />
        <TextInput label="To" type="date" value={to} onChange={(e) => reset(setTo)(e.currentTarget.value)} />
        <Select label="Type" placeholder="All" clearable value={type} onChange={reset(setType)}
          data={[{ value: "work", label: "Work" }, { value: "rest", label: "Break" }]} w={120} />
        <Select label="Source" placeholder="All" clearable value={source} onChange={reset(setSource)}
          data={[{ value: "timer", label: "Timer" }, { value: "manual", label: "Manual" }, { value: "import", label: "Import" }]}
          w={130} />
        <TextInput label="Search" leftSection={<IconSearch size={14} />} placeholder="Task, note" value={search}
          onChange={(e) => reset(setSearch)(e.currentTarget.value)} />
      </Group>
      <Text size="sm" c="dimmed">{total} session(s). Times and durations are immutable; notes, tags, outcome and the analytics toggle can change.</Text>
      {sessions.isLoading ? <Loader /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={900}>
            <Table verticalSpacing="xs" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>When</Table.Th>
                  <Table.Th>Task</Table.Th>
                  <Table.Th>Type</Table.Th>
                  <Table.Th>Active</Table.Th>
                  <Table.Th>Ended</Table.Th>
                  <Table.Th>Source</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(sessions.data?.items ?? []).map((s) => <SessionRow key={s.id} s={s} />)}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {total > PAGE_SIZE && <Pagination total={Math.ceil(total / PAGE_SIZE)} value={page} onChange={setPage} />}
      <LogSessionModal opened={logging} onClose={() => setLogging(false)} />
    </Stack>
  );
}
