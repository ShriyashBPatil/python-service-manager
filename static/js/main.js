document.addEventListener('DOMContentLoaded', function() {
    
    // Service actions (start, stop, restart, delete)
    const actionBtns = document.querySelectorAll('.action-btn');
    actionBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const action = this.getAttribute('data-action');
            const name = this.getAttribute('data-name');
            
            if (action === 'delete') {
                if (!confirm(`Are you sure you want to delete service '${name}'? This will stop and disable it.`)) {
                    return;
                }
            }
            
            // Send action to server
            fetch(`/action/${action}/${name}`, {
                method: 'POST'
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    location.reload(); // Reload to see updated status
                } else {
                    alert(`Action failed: ${data.message}`);
                }
            })
            .catch(err => {
                alert(`Error: ${err}`);
            });
        });
    });

    // Docker Stack / Application actions (start, stop, restart, up, down)
    const stackBtns = document.querySelectorAll('.btn-stack-action');
    stackBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const action = this.getAttribute('data-action');
            const stackId = this.getAttribute('data-stack');
            const stackName = this.getAttribute('data-name') || stackId;
            
            const originalText = this.innerHTML;
            this.disabled = true;
            this.innerHTML = `<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Working...`;

            fetch(`/docker/stack/${action}/${stackId}`, {
                method: 'POST'
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert(`Stack action failed: ${data.message}`);
                    this.disabled = false;
                    this.innerHTML = originalText;
                }
            })
            .catch(err => {
                alert(`Error performing stack action: ${err}`);
                this.disabled = false;
                this.innerHTML = originalText;
            });
        });
    });

    // File Browser Logic
    let currentTargetInput = null;
    let browserModal = null;
    let currentBrowserPath = "";
    let currentBrowserParent = "";

    const browseBtns = document.querySelectorAll('.btn-browse');
    if (browseBtns.length > 0) {
        browserModal = new bootstrap.Modal(document.getElementById('fileBrowserModal'));
    }

    browseBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const targetId = this.getAttribute('data-target');
            currentTargetInput = document.getElementById(targetId);
            const initialPath = currentTargetInput.value || "";
            
            // Open modal
            browserModal.show();
            loadDirectory(initialPath);
        });
    });

    const upBtn = document.getElementById('browserUpBtn');
    if (upBtn) {
        upBtn.addEventListener('click', function() {
            loadDirectory(currentBrowserParent);
        });
    }

    const selectBtn = document.getElementById('browserSelectBtn');
    if (selectBtn) {
        selectBtn.addEventListener('click', function() {
            if (currentTargetInput) {
                currentTargetInput.value = currentBrowserPath;
            }
            browserModal.hide();
        });
    }

    function loadDirectory(path) {
        fetch('/api/browse', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ path: path })
        })
        .then(res => res.json())
        .then(data => {
            const errorDiv = document.getElementById('browserError');
            if (data.error) {
                errorDiv.textContent = data.error;
                errorDiv.classList.remove('d-none');
            } else {
                errorDiv.classList.add('d-none');
            }

            currentBrowserPath = data.current_path;
            currentBrowserParent = data.parent;
            
            document.getElementById('browserCurrentPath').value = currentBrowserPath;
            
            const listDiv = document.getElementById('browserList');
            listDiv.innerHTML = '';
            
            // Render Directories
            data.directories.forEach(dir => {
                const a = document.createElement('a');
                a.className = 'list-group-item list-group-item-action cursor-pointer text-primary';
                a.innerHTML = `<i class="bi bi-folder-fill me-2"></i>${dir}`;
                a.addEventListener('click', function() {
                    const sep = currentBrowserPath.endsWith('/') || currentBrowserPath.endsWith('\\') ? '' : (currentBrowserPath.includes('\\') ? '\\' : '/');
                    loadDirectory(currentBrowserPath + sep + dir);
                });
                listDiv.appendChild(a);
            });
            
            // Render Files
            data.files.forEach(file => {
                const a = document.createElement('a');
                a.className = 'list-group-item list-group-item-action cursor-pointer text-secondary';
                a.innerHTML = `<i class="bi bi-file-earmark-text me-2"></i>${file}`;
                a.addEventListener('click', function() {
                    if (currentTargetInput) {
                        const sep = currentBrowserPath.endsWith('/') || currentBrowserPath.endsWith('\\') ? '' : (currentBrowserPath.includes('\\') ? '\\' : '/');
                        currentTargetInput.value = currentBrowserPath + sep + file;
                        browserModal.hide();
                    }
                });
                listDiv.appendChild(a);
            });
        })
        .catch(err => {
            console.error("Browser error", err);
        });
    }
});
