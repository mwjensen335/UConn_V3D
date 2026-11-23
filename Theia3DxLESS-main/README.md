# **Theia3D x LESS**

This repository contains a workflow to automatically score a jump landing task as captured with [Theia3D](https://www.theiamarkerless.ca/) using the Landing Error Scoring System ([LESS](https://journals.sagepub.com/doi/10.1177/0363546509343200)). A series of scripts are written using [Visual3D](https://www.has-motion.ca/biomechanics-software/#visual3d)’s internal scripting engine for motion capture data processing. The workflow is ideal for large-scale studies involving multiple subjects and trials, reducing manual effort and ensuring consistent data management.

This work is a result of a collaboration between Jereme Outerleys at Queen's University and Julie Burland at the University of Connecticut.

---

## **Table of Contents**

- [Features](#features)
- [Requirements](#requirements)
  - [Theia3D](#theia3d)
  - [Visual3D](#visual3d)
  - [Camera Setup](#camera-setup)
  - [Jump Task](#jump-task) 
- [Usage](#usage)
  - [Setup](#setup)
  - [File Structure](#file-structure)
  - [Script Execution](#script-execution)
- [Pipeline Overview](#pipeline-overview)
- [Phase Determination](#phase-determination)
- [Error Definitions](#error-definitions)
- [FAQ](#faq)
- [Planned Enhancements](#planned-enhancements)
- [License](#license)

---

## **Features**

- **Batch processing of Theia3D `.c3d` files**: Automatically scans directories and processes all files matching the `.c3d` format.
- **Dynamic folder navigation**: Leverages Theia3D's default folder hierarchy after batch processing to minimize the need for manual file management.
- **Conditional processing**: Automatically skips subjects already packaged into Visual3D workspaces.
- **File tagging**: Tags each motion capture file based on its content and folder structure.
- **Objective and consistent scoring**: Theia3D and Visual3D enhance the objectivity and reliability of scoring jump tasks. 
  
---

## **Requirements**

### Theia3D

**Theia3D processed c3d files**: Theia3D v2023.1.0.3160 with Model Version 10.0.0. has been tested. `.c3d` files must be structured in the Theia3D folder hierarchy which is default if TMBatch was used. See [File Structure](#file-structure).

#### **Important Considerations**
- Use max person = 1 in TMBatch to standardize pose_0 file being the subject under asssesment.
- Place origin of capture volume in a position that is closest to the subject under assessment, and use closest to origin in TMBatch.

### **Visual3D**

**Visual3D v2024.10.1 or higher**: The script relies on Visual3D’s internal scripting engine for motion capture data processing.

### **Camera Setup**
Careful camera setup will maximize data quality and reliability between locations.
The main purpose of the camera setup is to maximize subject visibilty in as many cameras as possible during the task but also maximizing subject height in terms of pixels.

```TO DO:

```

### **Jump Task**

The task begins with the subject standing on a 30-cm high box. The subject then jumps forward with both feet to a line on the floor. This line is at a distance equal to 50% of the subject’s height. Upon landing, the subject immediately rebounds upwards into a maximal vertical jump. This task is to be performed in a single fluid movement with minimal pause between the initial landing and the maximal vertical jump.

#### **Important Considerations**
- Minimize subject movement while on the box at the start of the trial.
- Have the subject stand shoulder width apart prior to the task.
- Confirm the subject is ready prior to each task.

---

## **Usage**

### **Setup**

1. **Get the repository**:
Either use `git clone https://github.com/yourusername/repositoryname.git` or [download the repository as a ZIP file](https://github.com/jouterleys/Theia3DxLESS/archive/refs/heads/main.zip). Ensure the file as been unzipped if downloaded as ZIP.
 
2. **Navigate to the Theia3DxLESS directory**:
Ensure you know where the v3d_scripts folder is located. Do not move or rename any of the `.v3s` scripts.

3. **Update the Set_Pipeline_Parameter_To_Folder_Path Parameter**:
The full file path to the v3d_scripts folder needs to be hardcoded in some of the `.v3s` scripts. Ensure it is changed in the following scripts: `00_build_cmz.v3s`, `0_call_script.v3s`, and `7_report_export.v3s`. The function is located at the top of these scripts. 

	```
	! Set path to call_script
	Set_Pipeline_Parameter_To_Folder_Path
	/PARAMETER_NAME=CALL_SCRIPT_SCRIPT_PATH
	/PARAMETER_VALUE=C:\Your\Path\To\Theia3DxLESS\v3d_scripts
	;
	```
 
### **File Structure**

Ensure the following folder structure which is the default if processed using TMBatch. All c3d files need to be in `_c3d` folder with the subject, action, trial folder hierarchy. A session or date level folder can also exist prior to the subject level folder.

```
example_c3d/                  
    ├── SUB001/  
    │   └── Jump/  
    │       ├── 00001/  
    │       │   ├── SUB001_Jump_00001_pose_0.c3d 
    │       │   └── SUB001_Jump_00001_pose_filt_0.c3d 
    │       └── 00002/
    │           ├── SUB001_Jump_00002_pose_0.c3d 
    │           └── SUB001_Jump_00002_pose_filt_0.c3d 
    ├── SUB002/  
    │   └── Jump/  
    │       ├── 00001/  
    │       │   ├── SUB002_Jump_00001_pose_0.c3d 
    │       │   └── SUB002_Jump_00001_pose_filt_0.c3d 
    │       └── 00002/
    │           ├── SUB002_Jump_00002_pose_0.c3d 
    │           └── SUB002_Jump_00002_pose_filt_0.c3d 

```
Or
```
example_c3d/                  
    ├── 2024-01-01/
    │   ├── SUB001/  
    │   │   └── Jump/  
    │   │       ├── 00001/  
    │   │       │   ├── SUB001_Jump_00001_pose_0.c3d 
    │   │       │   └── SUB001_Jump_00001_pose_filt_0.c3d 
    │   │       └── 00002/
    │   │           ├── SUB001_Jump_00002_pose_0.c3d 
    │   │           └── SUB001_Jump_00002_pose_filt_0.c3d 
    │   ├── SUB002/  
    │   │   └── Jump/  
    │   │       ├── 00001/  
    │   │       │   ├── SUB002_Jump_00001_pose_0.c3d 
    │   │       │   └── SUB002_Jump_00001_pose_filt_0.c3d 
    │   │       └── 00002/
    │   │           ├── SUB002_Jump_00002_pose_0.c3d 
    │   │           └── SUB002_Jump_00002_pose_filt_0.c3d
    ├── 2024-01-02/
    │   ├── SUB003/  
    │   │   └── Jump/  
    │   │       ├── 00001/  
    │   │       │   ├── SUB003_Jump_00001_pose_0.c3d 
    │   │       │   └── SUB003_Jump_00001_pose_filt_0.c3d 
    │   │       └── 00002/
    │   │           ├── SUB003_Jump_00002_pose_0.c3d 
    │   │           └── SUB003_Jump_00002_pose_filt_0.c3d 
    │   ├── SUB004/  
    │   │   └── Jump/  
    │   │       ├── 00001/  
    │   │       │   ├── SUB004_Jump_00001_pose_0.c3d 
    │   │       │   └── SUB004_Jump_00001_pose_filt_0.c3d 
    │   │       └── 00002/
    │   │           ├── SUB004_Jump_00002_pose_0.c3d 
    │   │           └── SUB004_Jump_00002_pose_filt_0.c3d

```

### **Script Execution**

1. **Visual3D**:
Open Visual3D and then the Pipeline Workshop. Click `Open Pipeline` and navigate to the `v3d_scripts` folder and select `00_build_cmz.v3s`

2. **Build CMZs and Score**:
Click Execute Pipeline. When prompted select the `_c3d` folder. `00_build_cmz.v3s` will automatically go through the `_c3d` folder and create `cmz` workspaces for each subject (assuming the [File Structure](#file-structure)). The `cmz` will be saved under the subject level folder. `00_build_cmz.v3s` also runs the `0_call_script.v3s` on each workspace after its built. `0_call_script.v3s` runs scripts 1 to 7.

 ## **Pipeline Overview**
 - `00_build_cmz.v3s` will automatically go through the `_c3d` folder and create `cmz` workspaces for each subject (assuming the [File Structure](#file-structure) above). The `cmz` will be saved under the subject level folder. `00_build_cmz.v3s` also runs the `0_call_script.v3s` on each workspace after its built.
 - `0_call_script.v3s` runs scripts `1_` to `7_`. This can be run on pre-built `cmz` workspaces.
 - `1_compute_model_based.v3s` calculates all the model based outcomes like joint and segment angles.
 - `2_events.v3s` determines the events of the jump task including initial contact and end of the landing phase.
 - `3_less_values.v3s` calculates the values of model based outcomes needed to determine the errors.
 - `4_less_errors.v3s` determines if errors are present based on the error definitions.
 - `5_less_totals.v3s` tallys the errors to calculate the LESS score on each trial.
 - `6_less_overall.v3s` determines the overall LESS score across all trials in the workspace.
 - `7_report_export.v3s` loads the report template into each workspace and exports the report as a text file.

---

## **Phase Determination**

- **Initial Contact:** Peak in vertical acceleration of foot center of gravity.

---

## **Error Definitions**

| Padua Item | TheiaLESS Item | Name | Error Definition |
|---|---|---|---|
| 1 | 1 | Knee Flexion | Knee is flexed less than 30 degrees at IC |
| 2 | 2 | Hip Flexion | Hip is flexed less than 30 degrees at IC |
| 3 | 3 | Trunk Flexion | Trunk is flexed less than 10 degrees at IC |
| 4 | 4 | Ankle PF | Foot segment angle at IC is greater than median standing foot angle 1 second before jump (i.e. If there is any dorsi-flexion relative to standing posture) |
| 5 | 5 | Knee Valgus | Knee Joint Center is More Medial than Ankle Joint Center, along a ML axis in pelvis |
| 6 | 6 | Trunk Lateral Flexion | Trunk is flexed laterally greater than 5 degrees at IC |
| 7 | 7 | Stance Width - Wide | Stance width is 15% greater than shoulder width |
| 8 | 8 | Stance Width - Narrow | Stance width is 12% less than shoulder width |
| 9 | 9 | Foot position - Toe In | Max Foot angle rotated internally greater than 10 degrees |
| 10 | 10 | Foot position - Toe Out | Max Foot angle rotated externally greater than 15 degrees |
| 11a | 11a | Asymmetrical Contact Timing | One foot lands at least 34 ms before the other at IC |
| 11b | 11b | Asymmetrical Contact Heel-Toe/ Toe-Heel | One foot has error in item 4 and other does not |
| 12 | 12 | Knee Flexion | Maximum Knee flexion is less than 65 degrees between IC and end of landing phase |
| 13 | 13 | Hip Flexion | Maximum Hip flexion is less than 45 degrees between IC and end of landing phase |
| 14 | 14 | Trunk Flexion | Maximum Trunk flexion is less than 10 degrees between IC and end of landing phase |
| 15 | 15 | Knee Valgus | Knee Joint Center is More Medial than Ankle Joint Center, along a ML axis in pelvis, and any point between IC and end of landing phase |
| 16 | 16 | Joint Displacement | Soft (0) = no errors in items 12, 13, or 14 <br> Average (1) = one error in items 12 or 13 or 14 <br> Stiff (2) = 2 or more errors in 12 or 13 or 14 |
| 17 | 17 | Overall Impression | Excellent (0) = soft joint displacement AND no errors for either 5 or 15 <br> Poor (1) = error for 12 or 13 or 14 AND error for either 5 or 15 <br> Average (2) = if not classified as Excellent or Poor |


---

## **FAQ**
Please submit an [Issue](https://github.com/jouterleys/Theia3DxLESS/issues/new/choose
)  if you have a question or problem. Frequently asked question will be added here as needed.

```TO DO:

```

---

## **Planned Enhancements**
 - Add values for the metrics (i.e. means or median angle) to report or for export.

---

## **License**

This project is licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License (CC BY-NC-SA 4.0)**.

You are free to:
- **Share** — copy and redistribute the material in any medium or format.
- **Adapt** — remix, transform, and build upon the material.

However, you must:
- **Give appropriate credit** to **Jereme Outerleys** (email: **jereme.outerleys@gmail.com**).
- **Not use the material for commercial purposes**.
- **Distribute any modifications under the same license**.

For more information, see the [LICENSE](./LICENSE) file or visit the [official license page](https://creativecommons.org/licenses/by-nc-sa/4.0/).

---
