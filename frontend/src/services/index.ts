import type { InterviewApi } from "../types/interview";
import { createHttpApi } from "./api";
import { config } from "./config";
import { createDemoApi } from "./demoApi";

/** The one API object the app uses. Demo mode swaps in sample data. */
export const api: InterviewApi = config.demoMode ? createDemoApi() : createHttpApi();
