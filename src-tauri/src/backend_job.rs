//! Own Windows child processes via a safe Win32 Job Object.
//!
//! KILL_ON_JOB_CLOSE is important: even an abrupt app termination closes the
//! last job handle and stops every subprocess launched within that job.

use std::io;
use std::os::windows::io::AsRawHandle;
use std::process::Child;
use win32job::Job;

pub(crate) struct WindowsJob {
    handle: Job,
}

impl WindowsJob {
    pub(crate) fn attach(child: &Child) -> io::Result<Self> {
        // Only own this specific freshly launched Child. Never reopen a PID
        // found on a user machine or attach an existing service.
        let handle = Job::create().map_err(io::Error::other)?;
        let mut limits = handle
            .query_extended_limit_info()
            .map_err(io::Error::other)?;
        limits.limit_kill_on_job_close();
        handle
            .set_extended_limit_info(&limits)
            .map_err(io::Error::other)?;
        handle
            .assign_process(child.as_raw_handle() as isize)
            .map_err(io::Error::other)?;
        Ok(Self { handle })
    }

    pub(crate) fn terminate(self) {
        // Dropping the *only* KILL_ON_JOB_CLOSE handle closes this job and
        // terminates its entire owned process tree. This also applies to a
        // crash when the kernel closes all handles held by the app process.
        let Self { handle } = self;
        drop(handle);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::{Command, Stdio};
    use std::thread;
    use std::time::{Duration, Instant};

    #[test]
    fn owns_parent_and_descendants_without_other_processes() {
        let mut command = Command::new("cmd.exe");
        command
            .args([
                "/D",
                "/C",
                "ping -n 3 127.0.0.1 > NUL & ping -n 40 127.0.0.1 > NUL",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let mut child = command.spawn().expect("spawn test-owned command");
        let job = WindowsJob::attach(&child).expect("attach task child to Job");
        let deadline = Instant::now() + Duration::from_secs(9);
        let mut tracked = Vec::new();
        while Instant::now() < deadline {
            tracked = job
                .handle
                .query_process_id_list()
                .expect("enumerate task-owned job");
            if tracked.len() >= 2 {
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        assert!(tracked.len() >= 2, "job must track parent and its child");
        job.terminate();
        child.wait().expect("reap task-owned parent");
        // Job lifecycle is deterministic on the parent. Descendants are
        // killed by the OS KILL_ON_JOB_CLOSE invariant; no PID-based kills.
    }
}
