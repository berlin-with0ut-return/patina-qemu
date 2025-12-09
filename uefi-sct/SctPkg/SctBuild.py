import argparse
import shutil

from edk2toolext.environment.uefi_build import UefiBuilder
from edk2toolext.invocables.edk2_setup import SetupSettingsManager
from edk2toolext.invocables.edk2_update import UpdateSettingsManager
from edk2toolext.invocables.edk2_platform_build import BuildSettingsManager
from edk2toolext.environment.shell_environment import GetEnvironment
from edk2toollib.windows.locate_tools import QueryVcVariables

from edk2toollib.utility_functions import RunCmd, RunPythonScript

from pathlib import Path
import logging

class SctBuildSettingsManager(SetupSettingsManager, UpdateSettingsManager, BuildSettingsManager, UefiBuilder):

    def AddCommandLineOptions(self, parser: argparse.ArgumentParser):
        parser.add_argument('--build-basetools', action='store_true', default=False, help='Build the base tools before building SCT')

    def RetrieveCommandLineOptions(self, args: argparse.Namespace):
        self.build_basetools = args.build_basetools

    def GetWorkspaceRoot(self):
        return str(Path(__file__).parent.parent)

    def GetActiveScopes(self):
        return ['edk2-build']

    def GetPackagesSupported(self):
        return ['SctPkg']

    def GetPackagesPath(self):
        return ('MU_BASECORE', self.GetWorkspaceRoot())

    def GetArchitecturesSupported(self):
        return ("AARCH64", "X64")

    def GetTargetsSupported(self):
        return ("DEBUG", "RELEASE")

    def SetPlatformEnv(self):
        logging.debug("PlatformBuilder SetPlatformEnv")

        self.env.SetValue("TOOL_CHAIN_TAG", "VS2022", "Platform Hardcoded")
        self.env.SetValue("ACTIVE_PLATFORM", "SctPkg/UEFI_SCT.dsc", "Platform Hardcoded")
        self.env.SetValue("TARGET_ARCH", "X64", "Platform Hardcoded")

        return 0

    def PlatformPreBuild(self):
        gen_bin = Path(self.edk2path.GetAbsolutePathOnThisSystemFromEdk2RelativePath("BaseTools"), "Bin", "Win32", "GenBin.exe")
        if self.build_basetools or not Path(gen_bin).exists():
            ret = self.BuildBaseTools()
            if ret != 0:
                return ret

            GetEnvironment().insert_path(str(gen_bin))
            GetEnvironment().set_shell_var("EDK_TOOLS_BIN", str(gen_bin))
        return 0

    def PlatformPostBuild(self):
        arch = self.env.GetValue("TARGET_ARCH")
        file = self.edk2path.GetAbsolutePathOnThisSystemFromEdk2RelativePath("SctPkg", "CommonGenFramework.bat")
        RunCmd(file, f"uefi_sct {arch} Install{arch}.efi", workingdir=self.env.GetValue("BUILD_OUTPUT_BASE"))
        return 0

    def BuildBaseTools(self):
        # Build BaseTools
        logging.info("Building BaseTools")
        toolchain = self.env.GetValue("TOOL_CHAIN_TAG")
        builder_path = self.edk2path.GetAbsolutePathOnThisSystemFromEdk2RelativePath("BaseTools", "Edk2ToolsBuild.py")
        ret = RunPythonScript(builder_path, f"-t {toolchain}")
        if ret != 0:
            logging.error("Failed to build BaseTools")
            return ret
        logging.info("BaseTools built successfully")

        # Build GenBin
        if self.env.GetValue("TARGET_ARCH") == "X64":
            VcToolChainArch = "x86"
        elif self.env.GetValue("TARGET_ARCH") == "AARCH64":
            VcToolChainArch = "arm64"
        else:
            logging.error(f"Unsupported architecture: {self.env.GetValue('TARGET_ARCH')}")
            return 1

        interesting_keys = ["ExtensionSdkDir", "INCLUDE", "LIB"]
        interesting_keys.extend(
            ["LIBPATH", "Path", "UniversalCRTSdkDir", "UCRTVersion", "WindowsLibPath", "WindowsSdkBinPath"])
        interesting_keys.extend(
            ["WindowsSdkDir", "WindowsSdkVerBinPath", "WindowsSDKVersion", "VCToolsInstallDir"])
        vc_vars = QueryVcVariables(
            interesting_keys, VcToolChainArch, vs_version=self.env.GetValue("TOOL_CHAIN_TAG").lower()) # MU_CHANGE
        for key in vc_vars.keys():
            logging.debug(f"Var - {key} = {vc_vars[key]}")
            if key.lower() == 'path':
                GetEnvironment().set_path(vc_vars[key])
            else:
                GetEnvironment().set_shell_var(key, vc_vars[key])

        logging.info("Building GenBin")
        genbin_src = Path(self.edk2path.GetAbsolutePathOnThisSystemFromEdk2RelativePath("SctPkg", "Tools", "Source", "GenBin"))
        genbin_dest = Path(self.edk2path.GetAbsolutePathOnThisSystemFromEdk2RelativePath("BaseTools", "Source", "C"), "GenBin")
        if genbin_dest.exists():
            shutil.rmtree(genbin_dest)

        shutil.copytree(genbin_src, genbin_dest)
        ret = RunCmd("nmake", "", workingdir=genbin_dest)
        if ret != 0:
            logging.error("Failed to build GenBin")
            return ret
        logging.info("GenBin built successfully")

        return 0
