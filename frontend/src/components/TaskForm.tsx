import {
  Autocomplete, Button, Group, Modal, MultiSelect, NumberInput, Select, SimpleGrid, Stack, Switch, TagsInput,
  Textarea, TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useEffect } from "react";
import { endpoints } from "../api/endpoints";
import type { Task, TaskInput } from "../api/types";
import { useAppMutation } from "../hooks/useFocus";
import { notifyOk } from "../lib/notify";

const RECURRENCE_PRESETS = [
  { value: "", label: "Does not repeat" },
  { value: "FREQ=DAILY", label: "Daily" },
  { value: "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", label: "Weekdays" },
  { value: "FREQ=WEEKLY", label: "Weekly (same weekday)" },
  { value: "FREQ=MONTHLY", label: "Monthly (same day)" },
  { value: "custom", label: "Custom RRULE…" },
];

interface Values {
  title: string;
  description: string;
  project_id: string | null;
  category: string;
  priority: string;
  status: string;
  estimated_minutes: number | string;
  deadline: string;
  earliest_start: string;
  planned_date: string;
  preferred_time: string | null;
  energy_requirement: string | null;
  importance: string | null;
  urgency: string | null;
  recurrence_preset: string;
  recurrence_rule: string;
  tags: string[];
  dependencies: string[];
  strict_dependencies: boolean;
}

const toLocalInput = (iso: string | null) => (iso ? dayjs(iso).format("YYYY-MM-DDTHH:mm") : "");
const fromLocalInput = (value: string) => (value ? dayjs(value).toISOString() : null);

function initial(task?: Task | null): Values {
  const rule = task?.recurrence_rule ?? "";
  const preset = RECURRENCE_PRESETS.some((p) => p.value === rule) ? rule : "custom";
  return {
    title: task?.title ?? "",
    description: task?.description ?? "",
    project_id: task?.project_id ?? null,
    category: task?.category ?? "",
    priority: task?.priority ?? "medium",
    status: task?.status ?? "planned",
    estimated_minutes: task?.estimated_minutes ?? "",
    deadline: toLocalInput(task?.deadline ?? null),
    earliest_start: toLocalInput(task?.earliest_start ?? null),
    planned_date: task?.planned_date ?? "",
    preferred_time: task?.preferred_time ?? null,
    energy_requirement: task?.energy_requirement ?? null,
    importance: task?.importance ? String(task.importance) : null,
    urgency: task?.urgency ? String(task.urgency) : null,
    recurrence_preset: rule ? preset : "",
    recurrence_rule: rule,
    tags: task?.tags ?? [],
    dependencies: task?.dependencies.map((d) => d.depends_on_id) ?? [],
    strict_dependencies: task?.dependencies.every((d) => d.strict) ?? true,
  };
}

function toPayload(v: Values): TaskInput {
  const rule = v.recurrence_preset === "custom" ? v.recurrence_rule.trim() : v.recurrence_preset;
  return {
    title: v.title.trim(),
    description: v.description.trim() || null,
    project_id: v.project_id || null,
    category: v.category.trim() || null,
    priority: v.priority as Task["priority"],
    status: v.status as Task["status"],
    estimated_minutes: v.estimated_minutes === "" ? null : Number(v.estimated_minutes),
    deadline: fromLocalInput(v.deadline),
    earliest_start: fromLocalInput(v.earliest_start),
    planned_date: v.planned_date || null,
    preferred_time: (v.preferred_time || null) as Task["preferred_time"],
    energy_requirement: (v.energy_requirement || null) as Task["energy_requirement"],
    importance: v.importance ? Number(v.importance) : null,
    urgency: v.urgency ? Number(v.urgency) : null,
    recurrence_rule: rule || null,
    tags: v.tags,
    dependencies: v.dependencies.map((id) => ({ depends_on_id: id, strict: v.strict_dependencies })),
  };
}

export function TaskForm({ opened, onClose, task }: { opened: boolean; onClose: () => void; task?: Task | null }) {
  const form = useForm<Values>({
    initialValues: initial(task),
    validate: { title: (v) => (v.trim() ? null : "Title is required") },
  });
  useEffect(() => {
    if (opened) form.setValues(initial(task));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, task?.id]);
  const projects = useQuery({ queryKey: ["projects", "active"], queryFn: () => endpoints.projects("active") });
  const categories = useQuery({ queryKey: ["categories"], queryFn: endpoints.categories });
  const openTasks = useQuery({
    queryKey: ["tasks", "open-for-deps"],
    queryFn: () => endpoints.tasks({ status: ["inbox", "planned", "in_progress", "blocked", "completed"] }),
    enabled: opened,
  });
  const save = useAppMutation(
    (payload: TaskInput) => (task ? endpoints.updateTask(task.id, payload) : endpoints.createTask(payload)),
    () => {
      notifyOk(task ? "Task updated" : "Task created");
      onClose();
    },
  );

  return (
    <Modal opened={opened} onClose={onClose} title={task ? "Edit task" : "New task"} size="xl">
      <form onSubmit={form.onSubmit((v) => save.mutate(toPayload(v)))}>
        <Stack>
          <TextInput label="Title" required data-autofocus {...form.getInputProps("title")} />
          <Textarea label="Description" autosize minRows={2} {...form.getInputProps("description")} />
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <Select label="Project" clearable searchable
              data={(projects.data ?? []).map((p) => ({ value: p.id, label: p.name }))}
              {...form.getInputProps("project_id")} />
            <Autocomplete label="Category" data={categories.data ?? []} {...form.getInputProps("category")} />
            <TagsInput label="Tags" {...form.getInputProps("tags")} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <Select label="Status" data={["inbox", "planned", "in_progress", "blocked", "completed", "cancelled"]}
              {...form.getInputProps("status")} />
            <Select label="Priority" data={["low", "medium", "high", "critical"]} {...form.getInputProps("priority")} />
            <Select label="Importance" clearable data={["1", "2", "3", "4", "5"]} {...form.getInputProps("importance")} />
            <Select label="Urgency" clearable data={["1", "2", "3", "4", "5"]} {...form.getInputProps("urgency")} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, sm: 4 }}>
            <NumberInput label="Estimate (min)" min={1} max={10000} {...form.getInputProps("estimated_minutes")} />
            <TextInput label="Planned for" type="date" {...form.getInputProps("planned_date")} />
            <TextInput label="Deadline" type="datetime-local" {...form.getInputProps("deadline")} />
            <TextInput label="Earliest start" type="datetime-local" {...form.getInputProps("earliest_start")} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <Select label="Preferred time" clearable data={["morning", "afternoon", "evening"]}
              {...form.getInputProps("preferred_time")} />
            <Select label="Energy needed" clearable data={["low", "medium", "high"]}
              {...form.getInputProps("energy_requirement")} />
            <Select label="Repeats" data={RECURRENCE_PRESETS} {...form.getInputProps("recurrence_preset")} />
          </SimpleGrid>
          {form.values.recurrence_preset === "custom" && (
            <TextInput label="RRULE" placeholder="FREQ=WEEKLY;BYDAY=MO,WE,TH,SA"
              description="RFC 5545 recurrence rule" {...form.getInputProps("recurrence_rule")} />
          )}
          <Group align="end" grow>
            <MultiSelect label="Depends on" searchable clearable
              data={(openTasks.data ?? []).filter((t) => t.id !== task?.id).map((t) => ({ value: t.id, label: t.title }))}
              {...form.getInputProps("dependencies")} />
            <Switch label="Strict (can't start before prerequisites are done)" style={{ flexGrow: 0 }}
              {...form.getInputProps("strict_dependencies", { type: "checkbox" })} />
          </Group>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={save.isPending}>{task ? "Save" : "Create task"}</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
