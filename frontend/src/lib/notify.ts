import { notifications } from "@mantine/notifications";
import { ApiError } from "../api/client";

export function notifyError(error: unknown) {
  const message = error instanceof ApiError ? error.message : error instanceof Error ? error.message : String(error);
  notifications.show({ color: "red", title: "Something went wrong", message });
}

export function notifyOk(message: string) {
  notifications.show({ color: "teal", message });
}
