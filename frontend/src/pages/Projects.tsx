import {
  ActionIcon, Badge, Button, ColorInput, Group, Loader, Menu, Modal, Paper, SegmentedControl, SimpleGrid, Stack, Text,
  Textarea, TextInput, Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { IconArchive, IconArchiveOff, IconDots, IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { endpoints } from "../api/endpoints";
import type { Project } from "../api/types";
import { useAppMutation } from "../hooks/useFocus";
import { formatDateTime, formatMinutes } from "../lib/format";
import { notifyOk } from "../lib/notify";

function ProjectForm({ opened, project, onClose }: { opened: boolean; project: Project | null; onClose: () => void }) {
  const form = useForm({
    initialValues: { name: "", description: "", color: "" },
    validate: { name: (v) => (v.trim() ? null : "Name is required") },
  });
  useEffect(() => {
    if (opened) {
      form.setValues({ name: project?.name ?? "", description: project?.description ?? "", color: project?.color ?? "" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, project?.id]);
  const save = useAppMutation(
    (v: typeof form.values) => {
      const body = { name: v.name.trim(), description: v.description.trim() || null, color: v.color || null };
      return project ? endpoints.updateProject(project.id, body) : endpoints.createProject(body);
    },
    () => {
      notifyOk(project ? "Project updated" : "Project created");
      onClose();
    },
  );
  return (
    <Modal opened={opened} onClose={onClose} title={project ? "Edit project" : "New project"}>
      <form onSubmit={form.onSubmit((v) => save.mutate(v))}>
        <Stack>
          <TextInput label="Name" required data-autofocus {...form.getInputProps("name")} />
          <Textarea label="Description" autosize minRows={2} {...form.getInputProps("description")} />
          <ColorInput label="Colour" format="hex" {...form.getInputProps("color")} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={save.isPending}>Save</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function ProjectCard({ project, onEdit }: { project: Project; onEdit: () => void }) {
  const stats = useQuery({ queryKey: ["projects", project.id, "stats"], queryFn: () => endpoints.projectStats(project.id) });
  const archived = project.status === "archived";
  const toggle = useAppMutation(
    () => endpoints.updateProject(project.id, { status: archived ? "active" : "archived" }),
    () => notifyOk(archived ? "Project restored" : "Project archived"),
  );
  const remove = useAppMutation(() => endpoints.deleteProject(project.id), () => notifyOk("Project deleted"));
  const s = stats.data;
  return (
    <Paper withBorder p="md" style={{ borderLeft: `4px solid ${project.color ?? "var(--mantine-color-gray-4)"}` }}>
      <Group justify="space-between" wrap="nowrap">
        <Group gap={6}>
          <Text fw={600}>{project.name}</Text>
          {archived && <Badge size="sm" color="gray">archived</Badge>}
        </Group>
        <Menu position="bottom-end">
          <Menu.Target><ActionIcon variant="subtle" color="gray"><IconDots size={16} /></ActionIcon></Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<IconPencil size={14} />} onClick={onEdit}>Edit</Menu.Item>
            <Menu.Item leftSection={archived ? <IconArchiveOff size={14} /> : <IconArchive size={14} />}
              onClick={() => toggle.mutate(undefined)}>
              {archived ? "Restore" : "Archive"}
            </Menu.Item>
            <Menu.Item color="red" leftSection={<IconTrash size={14} />}
              onClick={() => {
                if (window.confirm(`Delete project "${project.name}"? Projects with tasks or sessions can only be archived.`)) {
                  remove.mutate(undefined);
                }
              }}>
              Delete
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>
      {project.description && <Text size="sm" c="dimmed" mt={4}>{project.description}</Text>}
      {s ? (
        <SimpleGrid cols={2} mt="sm" spacing={4}>
          <Text size="sm">Focus <b>{formatMinutes(s.total_focus_minutes)}</b></Text>
          <Text size="sm">Sessions <b>{s.session_count}</b></Text>
          <Text size="sm">Done <b>{s.tasks_completed}</b> · open <b>{s.tasks_remaining}</b></Text>
          <Text size="sm">Remaining <b>{formatMinutes(s.estimated_remaining_minutes)}</b></Text>
          <Text size="xs" c="dimmed" style={{ gridColumn: "span 2" }}>
            Last worked {formatDateTime(s.last_worked_at)}
          </Text>
        </SimpleGrid>
      ) : <Loader size="xs" mt="sm" />}
    </Paper>
  );
}

export function ProjectsPage() {
  const [status, setStatus] = useState<"active" | "archived">("active");
  const [editing, setEditing] = useState<Project | null | undefined>(undefined);
  const projects = useQuery({ queryKey: ["projects", status], queryFn: () => endpoints.projects(status) });
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Projects</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing(null)}>New project</Button>
      </Group>
      <SegmentedControl w="fit-content" value={status} onChange={(v) => setStatus(v as "active" | "archived")}
        data={[{ value: "active", label: "Active" }, { value: "archived", label: "Archived" }]} />
      {projects.isLoading ? <Loader /> : (projects.data ?? []).length === 0 ? (
        <Text c="dimmed">No {status} projects.</Text>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
          {projects.data!.map((p) => <ProjectCard key={p.id} project={p} onEdit={() => setEditing(p)} />)}
        </SimpleGrid>
      )}
      <ProjectForm opened={editing !== undefined} project={editing ?? null} onClose={() => setEditing(undefined)} />
    </Stack>
  );
}
