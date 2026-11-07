//! Own the Windows backend process tree; killing only uvx leaves its children.

use std::io;
use std::mem::size_of;
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
use std::process::Child;
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

pub(crate) struct WindowsJob {
    handle: OwnedHandle,
}

impl WindowsJob {
    pub(crate) fn attach(child: &Child) -> io::Result<Self> {
        // SAFETY: CreateJobObjectW returns a newly owned handle, or null.
        let raw = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if raw.is_null() {
            return Err(io::Error::last_os_error());
        }
        let handle = unsafe { OwnedHandle::from_raw_handle(raw) };
        let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        // SAFETY: The input buffer has the documented C layout and exact size.
        if unsafe {
            SetInformationJobObject(
                handle.as_raw_handle(),
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const std::ffi::c_void,
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: Only the freshly launched Child handle is attached. Never
        // acquire or terminate a pre-existing PID or unrelated user service.
        if unsafe { AssignProcessToJobObject(handle.as_raw_handle(), child.as_raw_handle()) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self { handle })
    }

    pub(crate) fn terminate(&self) -> io::Result<()> {
        // SAFETY: Only this Job's child process tree can be terminated.
        if unsafe { TerminateJobObject(self.handle.as_raw_handle(), 1) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::{Command, Stdio};
    use std::thread;
    use std::time::{Duration, Instant};
    use windows_sys::Win32::System::JobObjects::{
        JobObjectBasicAccountingInformation, QueryInformationJobObject,
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
    };

    fn active_count(job: &WindowsJob) -> io::Result<u32> {
        let mut data = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION::default();
        // SAFETY: Valid owned job; correctly sized output buffer.
        let ok = unsafe {
            QueryInformationJobObject(
                job.handle.as_raw_handle(),
                JobObjectBasicAccountingInformation,
                &mut data as *mut _ as *mut std::ffi::c_void,
                size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                std::ptr::null_mut(),
            )
        };
        if ok == 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(data.ActiveProcesses)
        }
    }

    #[test]
    fn terminates_test_owned_parent_and_descendant() {
        // cmd starts ping as a child, with a bounded local-loopback workload.
        let mut cmd = Command::new("cmd.exe");
        cmd.args([
            "/D",
            "/C",
            "ping -n 3 127.0.0.1 > NUL & ping -n 40 127.0.0.1 > NUL",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
        let mut child = cmd.spawn().expect("spawn isolated test-only cmd");
        let job = WindowsJob::attach(&child).expect("attach child to job");
        let deadline = Instant::now() + Duration::from_secs(9);
        while Instant::now() < deadline && active_count(&job).unwrap_or(0) < 2 {
            thread::sleep(Duration::from_millis(100));
        }
        assert!(
            active_count(&job).unwrap() >= 2,
            "parent and ping must both belong to job"
        );
        job.terminate().expect("terminate owned subtree");
        child.wait().expect("reap child");
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline && active_count(&job).unwrap_or(1) != 0 {
            thread::sleep(Duration::from_millis(50));
        }
        assert_eq!(
            active_count(&job).unwrap(),
            0,
            "all task descendants stopped"
        );
    }
}
