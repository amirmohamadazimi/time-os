import {
  Alert, Badge, Button, Code, FileInput, Group, Loader, Paper, Select, SimpleGrid, Stack, Table, Text, Title,
} from "@mantine/core";
import { IconArrowBackUp, IconFileUpload } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { ImportReport } from "../api/types";
import { StatCard } from "../components/StatCard";
import { useAppMutation } from "../hooks/useFocus";
import { formatDateTime, formatMinutes } from "../lib/format";
import { notifyOk } from "../lib/notify";

const UNITS = [
  { value: "auto", label: "Detect automatically" },
  { value: "seconds", label: "Seconds" },
  { value: "minutes", label: "Minutes" },
  { value: "milliseconds", label: "Milliseconds" },
];
const STATUS_COLOR = { imported: "teal", duplicate: "yellow", invalid: "red" } as const;

function timezones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC"];
  }
}

function Report({ report }: { report: ImportReport }) {
  const s = report.summary;
  return (
    <Stack>
      {s.file_previously_imported && (
        <Alert color="yellow">This exact file was imported before. Rows already in the database are reported as duplicates.</Alert>
      )}
      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <StatCard label="Rows read" value={s.rows_read} />
        <StatCard label={report.dry_run ? "Would import" : "Imported"} value={s.valid}
          hint={`${s.work_sessions} work · ${s.rest_sessions} rest`} />
        <StatCard label="Duplicates" value={s.duplicates} hint="skipped" />
        <StatCard label="Invalid rows" value={s.invalid} hint="skipped, kept in the report" />
        <StatCard label="Focus hours" value={s.total_focus_hours} hint={`${s.total_rest_hours} h rest`} />
        <StatCard label="Work session" value={formatMinutes(s.avg_work_session_minutes)}
          hint={`median ${formatMinutes(s.median_work_session_minutes)}`} />
        <StatCard label="Flagged" value={s.flagged} hint={`${s.excluded_from_stats} excluded from analytics`} />
        <StatCard label="Date range" value={<Text size="sm" fw={600}>{formatDateTime(s.first_session)}</Text>}
          hint={`to ${formatDateTime(s.last_session)}`} />
      </SimpleGrid>
      <Paper withBorder p="md">
        <Text size="sm">
          Durations read as <b>{s.duration_unit}</b>.{" "}
          {s.assumed_timezone_rows > 0 && <>{s.assumed_timezone_rows} row(s) had no timezone and used the one selected above. </>}
        </Text>
        <Text size="sm" mt={4}>
          Columns: {Object.entries(s.columns_detected).map(([field, col]) => (
            <Badge key={field} variant="light" color="gray" mr={4}>{field} ← {col}</Badge>
          ))}
        </Text>
        {Object.keys(s.warnings_by_code).length > 0 && (
          <Text size="sm" mt={4}>Warnings: {Object.entries(s.warnings_by_code).map(([c, n]) => `${c} (${n})`).join(", ")}</Text>
        )}
        {Object.keys(s.errors_by_code).length > 0 && (
          <Text size="sm" mt={4} c="red">Errors: {Object.entries(s.errors_by_code).map(([c, n]) => `${c} (${n})`).join(", ")}</Text>
        )}
      </Paper>
      {report.issues.length > 0 && (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={800}>
            <Table verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Row</Table.Th>
                  <Table.Th>Result</Table.Th>
                  <Table.Th>Issues</Table.Th>
                  <Table.Th>Raw data</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {report.issues.map((i) => (
                  <Table.Tr key={i.row_number}>
                    <Table.Td>{i.row_number}</Table.Td>
                    <Table.Td><Badge color={STATUS_COLOR[i.status]} variant="light">{i.status}</Badge></Table.Td>
                    <Table.Td>
                      {i.errors.map((e) => <Text key={e} size="xs" c="red">{e}</Text>)}
                      {i.warnings.map((w) => <Text key={w} size="xs" c="dimmed">{w}</Text>)}
                    </Table.Td>
                    <Table.Td>
                      <Code block style={{ maxWidth: 420, whiteSpace: "pre-wrap", fontSize: 11 }}>
                        {Object.entries(i.raw).map(([k, v]) => `${k}: ${v ?? ""}`).join("\n")}
                      </Code>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
    </Stack>
  );
}

function History() {
  const batches = useQuery({ queryKey: ["imports"], queryFn: endpoints.imports });
  const rollback = useAppMutation(endpoints.rollbackImport, () => notifyOk("Import rolled back"));
  if (batches.isLoading) return <Loader />;
  const items = batches.data ?? [];
  return (
    <Paper withBorder p="md">
      <Title order={4} mb="xs">Previous imports</Title>
      {items.length === 0 ? <Text size="sm" c="dimmed">No imports yet.</Text> : (
        <Table.ScrollContainer minWidth={700}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>When</Table.Th>
                <Table.Th>File</Table.Th>
                <Table.Th>Imported</Table.Th>
                <Table.Th>Duplicates · invalid</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((b) => (
                <Table.Tr key={b.id} style={b.rolled_back_at ? { opacity: 0.6 } : undefined}>
                  <Table.Td>{formatDateTime(b.created_at)}</Table.Td>
                  <Table.Td>{b.filename}</Table.Td>
                  <Table.Td>{b.summary.valid ?? "–"}</Table.Td>
                  <Table.Td>{b.summary.duplicates ?? 0} · {b.summary.invalid ?? 0}</Table.Td>
                  <Table.Td>
                    {b.rolled_back_at ? <Badge color="gray">rolled back {formatDateTime(b.rolled_back_at)}</Badge> : (
                      <Button size="xs" variant="subtle" color="red" leftSection={<IconArrowBackUp size={14} />}
                        loading={rollback.isPending && rollback.variables === b.id}
                        onClick={() => {
                          if (window.confirm(`Roll back "${b.filename}"? Its ${b.summary.valid ?? ""} sessions are removed from history and analytics.`)) {
                            rollback.mutate(b.id);
                          }
                        }}>
                        Roll back
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Paper>
  );
}

export function ImportPage() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: endpoints.settings });
  const [file, setFile] = useState<File | null>(null);
  const [timezone, setTimezone] = useState<string | null>(null);
  const [unit, setUnit] = useState<string>("auto");
  const [report, setReport] = useState<ImportReport | null>(null);
  const [fileError, setFileError] = useState<ApiError | null>(null);
  const tz = timezone ?? settings.data?.timezone ?? "UTC";
  const run = useAppMutation(
    (dryRun: boolean) => endpoints.importSessions(file!, { dry_run: dryRun, default_timezone: tz, duration_unit: unit }),
    (r) => {
      setReport(r);
      setFileError(null);
      if (!r.dry_run) notifyOk(`Imported ${r.summary.valid} session(s)`);
    },
  );
  const reset = (f: File | null) => {
    setFile(f);
    setReport(null);
    setFileError(null);
  };
  return (
    <Stack>
      <Title order={2}>Import focus history</Title>
      <Text c="dimmed" size="sm">
        Upload a CSV export from your focus app. Preview first: nothing is saved until you confirm, and every import can be rolled back.
      </Text>
      <Paper withBorder p="md">
        <Group align="end">
          <FileInput style={{ flex: 1, minWidth: 240 }} label="CSV file" placeholder="Choose a .csv export" accept=".csv,text/csv"
            leftSection={<IconFileUpload size={16} />} value={file} onChange={reset} clearable />
          <Select label="Timezone for timestamps without one" searchable data={timezones()} value={tz}
            onChange={(v) => { setTimezone(v); setReport(null); }} w={260} />
          <Select label="Duration unit" data={UNITS} value={unit} allowDeselect={false}
            onChange={(v) => { setUnit(v ?? "auto"); setReport(null); }} w={200} />
          <Button variant="light" disabled={!file} loading={run.isPending && run.variables === true}
            onClick={() => run.mutate(true, {
              onError: (e) => setFileError(e instanceof ApiError ? e : null),
            })}>
            Preview
          </Button>
          <Button disabled={!report?.dry_run || report.summary.valid === 0} loading={run.isPending && run.variables === false}
            onClick={() => run.mutate(false)}>
            Import {report?.dry_run ? report.summary.valid : ""} sessions
          </Button>
        </Group>
      </Paper>
      {fileError?.details != null && (
        <Alert color="red" title={fileError.message}>
          <Code block>{JSON.stringify(fileError.details, null, 2)}</Code>
        </Alert>
      )}
      {report && (
        <>
          {!report.dry_run && <Alert color="teal">Import saved. You can roll it back below.</Alert>}
          <Report report={report} />
        </>
      )}
      <History />
    </Stack>
  );
}
