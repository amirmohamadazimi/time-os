import { BarChart, DonutChart } from "@mantine/charts";
import {
  Alert, Badge, Grid, Group, List, Loader, Paper, SegmentedControl, Select, SimpleGrid, Stack, Table, Text, Title,
  Tooltip,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { endpoints, type Range } from "../api/endpoints";
import { StatCard } from "../components/StatCard";
import { formatMinutes, formatPercent } from "../lib/format";

const PRESETS: Record<string, { label: string; days: number | null }> = {
  "7": { label: "7 days", days: 7 },
  "30": { label: "30 days", days: 30 },
  "90": { label: "90 days", days: 90 },
  "365": { label: "Year", days: 365 },
  all: { label: "All time", days: null },
};
const COLORS = ["indigo.6", "teal.6", "orange.6", "grape.6", "cyan.6", "pink.6", "lime.6", "yellow.6", "gray.6"];
const minutes = (v: number) => formatMinutes(v);

function useRange(preset: string, projectId: string | null): Range {
  return useMemo(() => {
    const days = PRESETS[preset].days;
    return {
      from: days ? dayjs().subtract(days - 1, "day").format("YYYY-MM-DD") : undefined,
      to: dayjs().format("YYYY-MM-DD"),
      project_id: projectId ?? undefined,
    };
  }, [preset, projectId]);
}

function Overview({ range }: { range: Range }) {
  const summary = useQuery({ queryKey: ["analytics", "summary", range], queryFn: () => endpoints.summary(range) });
  if (summary.isLoading) return <Loader />;
  if (!summary.data) return null;
  const s = summary.data;
  const pva = s.planned_vs_actual;
  return (
    <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }}>
      <StatCard label="Focus" value={formatMinutes(s.total_focus_minutes)} hint={`${s.session_count} work sessions`} />
      <StatCard label="Daily average" value={formatMinutes(s.avg_daily_focus_minutes)} hint={`${s.active_days} active days`} />
      <StatCard label="Session length" value={formatMinutes(s.avg_session_minutes)}
        hint={`median ${formatMinutes(s.median_session_minutes)} · longest ${formatMinutes(s.longest_session_minutes)}`} />
      <StatCard label="Completion rate" value={formatPercent(s.completion_rate)}
        hint={`${s.completed_sessions} completed · ${s.stopped_sessions} stopped`} />
      <StatCard label="Interrupted" value={formatPercent(s.interruption_rate)}
        hint={`${formatMinutes(s.total_paused_minutes)} paused in total`} />
      <StatCard label="Estimated → actual" value={pva.tasks ? `${formatMinutes(pva.estimated_minutes)} → ${formatMinutes(pva.actual_minutes)}` : "–"}
        hint={`${pva.tasks} completed task(s) with estimates`} />
    </SimpleGrid>
  );
}

function Trend({ range }: { range: Range }) {
  const days = range.from ? dayjs(range.to).diff(dayjs(range.from), "day") + 1 : 9999;
  const granularity = days <= 45 ? "day" : days <= 200 ? "week" : "month";
  const series = useQuery({
    queryKey: ["analytics", "timeseries", range, granularity],
    queryFn: () => endpoints.timeseries(range, granularity),
  });
  return (
    <Paper withBorder p="md">
      <Title order={5}>Focus per {granularity}</Title>
      {series.data && (
        <BarChart h={240} mt="sm" data={series.data.items} dataKey="period" valueFormatter={minutes}
          series={[{ name: "focus_minutes", label: "Focus", color: "indigo.6" }]} />
      )}
    </Paper>
  );
}

function Rhythm({ range }: { range: Range }) {
  const hours = useQuery({ queryKey: ["analytics", "by-hour", range], queryFn: () => endpoints.byHour(range) });
  const weekdays = useQuery({ queryKey: ["analytics", "by-weekday", range], queryFn: () => endpoints.byWeekday(range) });
  return (
    <Grid>
      <Grid.Col span={{ base: 12, md: 7 }}>
        <Paper withBorder p="md">
          <Title order={5}>By hour of day</Title>
          <Text size="xs" c="dimmed">Minutes are spread across the hours each session covered, in its own local time.</Text>
          {hours.data && (
            <BarChart h={220} mt="sm" valueFormatter={minutes} dataKey="label"
              data={hours.data.items.map((h) => ({ ...h, label: String(h.hour).padStart(2, "0") }))}
              series={[{ name: "focus_minutes", label: "Focus", color: "teal.6" }]} />
          )}
        </Paper>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 5 }}>
        <Paper withBorder p="md">
          <Title order={5}>Average day by weekday</Title>
          <Text size="xs" c="dimmed">Focus per calendar day, including days with no sessions.</Text>
          {weekdays.data && (
            <BarChart h={220} mt="sm" valueFormatter={minutes} dataKey="short"
              data={weekdays.data.items.map((w) => ({ ...w, short: w.name.slice(0, 3), avg: w.avg_daily_focus_minutes ?? 0 }))}
              series={[{ name: "avg", label: "Average focus", color: "grape.6" }]} />
          )}
        </Paper>
      </Grid.Col>
    </Grid>
  );
}

function Allocation({ range }: { range: Range }) {
  const projects = useQuery({ queryKey: ["analytics", "by-project", range], queryFn: () => endpoints.byProject(range) });
  const tags = useQuery({ queryKey: ["analytics", "by-tag", range], queryFn: () => endpoints.byTag(range) });
  const donut = (items: { name: string; value: number }[]) =>
    items.slice(0, COLORS.length).map((item, i) => ({ ...item, color: COLORS[i] }));
  return (
    <SimpleGrid cols={{ base: 1, md: 2 }}>
      <Paper withBorder p="md">
        <Title order={5} mb="sm">Time by project</Title>
        {projects.data && projects.data.items.length > 0 ? (
          <Group align="center" wrap="nowrap">
            <DonutChart size={160} thickness={24} valueFormatter={minutes}
              data={donut(projects.data.items.map((p) => ({ name: p.project_name, value: p.focus_minutes })))} />
            <Stack gap={2} style={{ flex: 1 }}>
              {projects.data.items.slice(0, 8).map((p) => (
                <Group key={p.project_id ?? "none"} justify="space-between">
                  <Text size="sm" truncate>{p.project_name}</Text>
                  <Text size="sm">{formatMinutes(p.focus_minutes)} · {formatPercent(p.share)}</Text>
                </Group>
              ))}
            </Stack>
          </Group>
        ) : <Text size="sm" c="dimmed">No sessions in this range.</Text>}
      </Paper>
      <Paper withBorder p="md">
        <Title order={5} mb="sm">Time by tag</Title>
        <Text size="xs" c="dimmed" mb="xs">A session with several tags counts toward each, so shares can add up to more than 100%.</Text>
        {tags.data && tags.data.items.length > 0 ? (
          <Stack gap={2}>
            {tags.data.items.slice(0, 10).map((t) => (
              <Group key={t.tag} justify="space-between">
                <Text size="sm">#{t.tag}</Text>
                <Text size="sm">{formatMinutes(t.focus_minutes)} · {formatPercent(t.share)} · {t.sessions} sessions</Text>
              </Group>
            ))}
          </Stack>
        ) : <Text size="sm" c="dimmed">No tagged sessions in this range.</Text>}
      </Paper>
    </SimpleGrid>
  );
}

const CONFIDENCE_COLOR = { insufficient: "gray", moderate: "yellow", strong: "teal" } as const;

function Estimation() {
  const [groupBy, setGroupBy] = useState<"category" | "project">("category");
  const est = useQuery({ queryKey: ["analytics", "estimation", groupBy], queryFn: () => endpoints.estimation(groupBy) });
  return (
    <Paper withBorder p="md">
      <Group justify="space-between">
        <div>
          <Title order={5}>Estimates vs actual</Title>
          <Text size="xs" c="dimmed">
            Completed tasks with an estimate and logged focus time. The multiplier stays near 1.0 until there are enough samples.
          </Text>
        </div>
        <SegmentedControl size="xs" value={groupBy} onChange={(v) => setGroupBy(v as "category" | "project")}
          data={[{ value: "category", label: "By category" }, { value: "project", label: "By project" }]} />
      </Group>
      {est.data && est.data.items.length > 0 ? (
        <Table.ScrollContainer minWidth={700}>
          <Table mt="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{groupBy === "category" ? "Category" : "Project"}</Table.Th>
                <Table.Th>Tasks</Table.Th>
                <Table.Th>Avg estimate → actual</Table.Th>
                <Table.Th>Ratio</Table.Th>
                <Table.Th>Planning multiplier</Table.Th>
                <Table.Th>Confidence</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {est.data.items.map((r) => (
                <Table.Tr key={r.group}>
                  <Table.Td>{r.group}</Table.Td>
                  <Table.Td>{r.samples}</Table.Td>
                  <Table.Td>{formatMinutes(r.avg_estimate_minutes)} → {formatMinutes(r.avg_actual_minutes)}</Table.Td>
                  <Table.Td>
                    <Tooltip label={`median per-task ratio ${r.median_ratio}`}>
                      <Text size="sm" c={r.tendency === "underestimate" ? "orange" : r.tendency === "overestimate" ? "blue" : undefined}>
                        ×{r.ratio} ({r.tendency})
                      </Text>
                    </Tooltip>
                  </Table.Td>
                  <Table.Td>×{r.multiplier}</Table.Td>
                  <Table.Td><Badge color={CONFIDENCE_COLOR[r.confidence]} variant="light">{r.confidence}</Badge></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      ) : <Text size="sm" c="dimmed" mt="sm">No completed tasks with estimates and focus time yet.</Text>}
    </Paper>
  );
}

function Patterns({ range }: { range: Range }) {
  const patterns = useQuery({ queryKey: ["analytics", "patterns", range], queryFn: () => endpoints.patterns(range) });
  return (
    <Paper withBorder p="md">
      <Group gap="xs">
        <Title order={5}>Patterns</Title>
        <Badge variant="outline" color="gray">Observed</Badge>
      </Group>
      <Text size="xs" c="dimmed" mb="xs">Computed directly from your sessions. These describe what happened, not why.</Text>
      {patterns.data && patterns.data.items.length > 0 ? (
        <List spacing={6}>
          {patterns.data.items.map((p) => (
            <List.Item key={p.id}>
              <Text size="sm">{p.statement} <Text span size="xs" c="dimmed">(n = {p.sample_size})</Text></Text>
            </List.Item>
          ))}
        </List>
      ) : <Text size="sm" c="dimmed">Not enough sessions in this range to report patterns.</Text>}
    </Paper>
  );
}

export function AnalyticsPage() {
  const [preset, setPreset] = useState("30");
  const [projectId, setProjectId] = useState<string | null>(null);
  const projects = useQuery({ queryKey: ["projects", "all"], queryFn: () => endpoints.projects() });
  const range = useRange(preset, projectId);
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Analytics</Title>
        <Group>
          <Select placeholder="All projects" clearable value={projectId} onChange={setProjectId}
            data={(projects.data ?? []).map((p) => ({ value: p.id, label: p.name }))} />
          <SegmentedControl value={preset} onChange={setPreset}
            data={Object.entries(PRESETS).map(([value, { label }]) => ({ value, label }))} />
        </Group>
      </Group>
      <Alert variant="light" color="gray">
        Sessions marked "exclude from stats" (for example, implausibly long imported ones) are left out of every number here.
      </Alert>
      <Overview range={range} />
      <Trend range={range} />
      <Rhythm range={range} />
      <Allocation range={range} />
      <Patterns range={range} />
      <Estimation />
    </Stack>
  );
}
