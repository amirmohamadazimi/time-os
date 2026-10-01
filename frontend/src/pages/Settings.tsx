import {
  ActionIcon, Alert, Button, Chip, Group, Loader, NumberInput, Paper, PasswordInput, Select, SimpleGrid, Stack, Switch,
  Text, TextInput, Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { IconPlus, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getToken, setToken } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { UserSettings } from "../api/types";
import { useAppMutation } from "../hooks/useFocus";
import { notifyOk } from "../lib/notify";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const hhmm = (t: string) => t.slice(0, 5);

function timezones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC"];
  }
}

function normalise(s: UserSettings): UserSettings {
  return {
    ...s,
    working_hours: { ...s.working_hours, start: hhmm(s.working_hours.start), end: hhmm(s.working_hours.end) },
    scheduler: {
      ...s.scheduler,
      meals: s.scheduler.meals.map((m) => ({ ...m, start: hhmm(m.start), end: hhmm(m.end) })),
    },
  };
}

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <Paper withBorder p="md">
      <Title order={4}>{title}</Title>
      {description && <Text size="sm" c="dimmed" mb="sm">{description}</Text>}
      <Stack gap="sm" mt={description ? 0 : "sm"}>{children}</Stack>
    </Paper>
  );
}

/** Stored in this browser only, and sent as a Bearer token when the server sets TIMEOS_API_TOKEN. */
function AccessToken() {
  const [value, setValue] = useState(getToken() ?? "");
  return (
    <Section title="API access token"
      description="Only needed when the server is started with TIMEOS_API_TOKEN. Kept in this browser's local storage.">
      <Group align="end">
        <PasswordInput style={{ flex: 1 }} label="Token" value={value} onChange={(e) => setValue(e.currentTarget.value)} />
        <Button variant="light" onClick={() => {
          setToken(value.trim() || null);
          notifyOk(value.trim() ? "Token saved for this browser" : "Token removed");
          window.location.reload();
        }}>
          Save token
        </Button>
      </Group>
    </Section>
  );
}

export function SettingsPage() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: endpoints.settings });
  const form = useForm<UserSettings>({ mode: "controlled" });
  useEffect(() => {
    if (settings.data) form.setValues(normalise(settings.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.data]);
  const save = useAppMutation(
    (v: UserSettings) => endpoints.updateSettings(v as unknown as Record<string, unknown>),
    () => notifyOk("Settings saved"),
  );
  if (settings.isLoading) return <Loader />;
  if (settings.error) {
    return (
      <Stack>
        <Alert color="red" title="Cannot load settings">{String(settings.error)}</Alert>
        <AccessToken />
      </Stack>
    );
  }
  if (!form.values.working_hours) return <Loader />;
  const v = form.values;
  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))}>
      <Stack>
        <Group justify="space-between">
          <Title order={2}>Settings</Title>
          <Button type="submit" loading={save.isPending}>Save settings</Button>
        </Group>
        <Section title="Time" description="Used for day boundaries, analytics by local time and timestamps without a timezone.">
          <Select label="Timezone" searchable data={timezones()} allowDeselect={false} {...form.getInputProps("timezone")} />
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <TextInput label="Working day starts" type="time" {...form.getInputProps("working_hours.start")} />
            <TextInput label="Working day ends" type="time" {...form.getInputProps("working_hours.end")} />
          </SimpleGrid>
          <Chip.Group multiple value={v.working_hours.days.map(String)}
            onChange={(days) => form.setFieldValue("working_hours.days", days.map(Number).sort())}>
            <Group gap={6}>
              {DAYS.map((d, i) => <Chip key={d} value={String(i)} size="sm">{d}</Chip>)}
            </Group>
          </Chip.Group>
        </Section>
        <Section title="Focus timer">
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <NumberInput label="Work session (min)" min={5} max={240} {...form.getInputProps("focus.work_minutes")} />
            <NumberInput label="Break (min)" min={1} max={120} {...form.getInputProps("focus.break_minutes")} />
          </SimpleGrid>
        </Section>
        <Section title="AI and automation"
          description="Claude works through the same validated actions as the app. These control how much it may do on its own.">
          <Switch label="AI-created tasks need my approval before they count"
            {...form.getInputProps("require_approval_for_ai_tasks", { type: "checkbox" })} />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select label="Scheduling" allowDeselect={false} {...form.getInputProps("scheduling_mode")} data={[
              { value: "manual", label: "Manual: I plan everything" },
              { value: "suggest", label: "Suggest: propose plans for me to accept" },
              { value: "auto", label: "Automatic: apply plans that pass validation" },
            ]} />
            <Select label="Google Calendar" allowDeselect={false} {...form.getInputProps("calendar_mode")} data={[
              { value: "read_only", label: "Read only" },
              { value: "suggest", label: "Suggest focus blocks" },
              { value: "auto_create", label: "Create focus blocks automatically" },
            ]} description="Events you created yourself are never changed automatically." />
          </SimpleGrid>
        </Section>
        <Section title="Scheduler" description="Used when building and repairing daily plans.">
          <SimpleGrid cols={{ base: 2, sm: 5 }}>
            <NumberInput label="Buffer ratio" min={0} max={0.6} step={0.05} decimalScale={2}
              {...form.getInputProps("scheduler.buffer_ratio")} />
            <NumberInput label="Max focus block (min)" min={15} max={240} {...form.getInputProps("scheduler.max_focus_minutes")} />
            <NumberInput label="Break between (min)" min={0} max={60} {...form.getInputProps("scheduler.break_minutes")} />
            <NumberInput label="Transition (min)" min={0} max={30} {...form.getInputProps("scheduler.transition_minutes")} />
            <NumberInput label="Shortest block (min)" min={5} max={120} {...form.getInputProps("scheduler.min_block_minutes")} />
          </SimpleGrid>
          <Text size="sm" fw={500}>Meals and protected time</Text>
          {v.scheduler.meals.map((_, i) => (
            <Group key={i} align="end">
              <TextInput label="Label" {...form.getInputProps(`scheduler.meals.${i}.label`)} />
              <TextInput label="From" type="time" {...form.getInputProps(`scheduler.meals.${i}.start`)} />
              <TextInput label="To" type="time" {...form.getInputProps(`scheduler.meals.${i}.end`)} />
              <ActionIcon variant="subtle" color="red" mb={4} onClick={() => form.removeListItem("scheduler.meals", i)}>
                <IconTrash size={16} />
              </ActionIcon>
            </Group>
          ))}
          <Button variant="subtle" w="fit-content" leftSection={<IconPlus size={14} />}
            onClick={() => form.insertListItem("scheduler.meals", { label: "Break", start: "15:00", end: "15:15" })}>
            Add protected time
          </Button>
        </Section>
        <Section title="Estimate learning"
          description="How historical estimate accuracy turns into planning multipliers. Fewer samples keep the multiplier near 1.0.">
          <SimpleGrid cols={{ base: 2, sm: 5 }}>
            <NumberInput label="Min samples" min={1} {...form.getInputProps("personalization.min_samples")} />
            <NumberInput label="Strong at" min={1} {...form.getInputProps("personalization.strong_samples")} />
            <NumberInput label="Prior strength" min={0.1} step={1} {...form.getInputProps("personalization.prior_strength")} />
            <NumberInput label="Min multiplier" min={0.1} step={0.1} decimalScale={2}
              {...form.getInputProps("personalization.min_multiplier")} />
            <NumberInput label="Max multiplier" min={0.1} step={0.1} decimalScale={2}
              {...form.getInputProps("personalization.max_multiplier")} />
          </SimpleGrid>
        </Section>
        <Section title="Import quality rules" description="Flags applied to imported sessions. Flagged sessions stay visible but can be excluded from analytics.">
          <SimpleGrid cols={{ base: 2, sm: 5 }}>
            <NumberInput label="Shortest real session (s)" min={0} max={600}
              {...form.getInputProps("import_rules.short_session_seconds")} />
            <NumberInput label="Long session (min)" min={30} {...form.getInputProps("import_rules.long_active_minutes")} />
            <NumberInput label="Long pause (min)" min={5} {...form.getInputProps("import_rules.long_pause_minutes")} />
            <NumberInput label="Implausible length (h)" min={2} {...form.getInputProps("import_rules.implausible_elapsed_hours")} />
            <NumberInput label="Duplicate tolerance (s)" min={0} max={3600}
              {...form.getInputProps("import_rules.duplicate_tolerance_seconds")} />
          </SimpleGrid>
        </Section>
        <AccessToken />
      </Stack>
    </form>
  );
}
