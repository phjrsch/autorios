# -----------------------------------------------------------------------------
#
# SPDX-License-Identifier: MIT
#
# This file is part of the autorios project
#
# Detailed license information can be found in LICENSE
# at the top level directory.
#
# -----------------------------------------------------------------------------


from __future__ import annotations
from typing import List,NamedTuple,Dict,Any,Union
import time
import sys
import csv
import logging
import copy
from pathlib import Path
from abc import ABC
import logging
from comtypes import COMError
import datetime
import threading
import sys
import warnings
warnings.simplefilter("ignore", UserWarning)
sys.coinit_flags = 2

#3rd party imports
from pywinauto import keyboard,Desktop, base_wrapper
from pywinauto.application import Application
import pywinauto.timings

#local imports
from .application import (MyApplication,ElementNotFoundError,
    wait_until_element_exists)
from .protocol import Protocol,STEP_TYPE
from .pyqtgui import (show_warning_messagebox,show_yesno_messagebox,
                      show_error_messagebox)
from .experiment_info import ExperimentInfo
from .device_settings import TriosDeviceSettings
from .settings import Settings,SETTING_VALUE_NOT_SET
from .specimen import Specimen
from .utility import write_float_to_input,write_to_input,is_button
from .datalogger import DataLogger

logger = logging.getLogger(__name__)

class StopException(Exception):
    pass

class TRIOS(MyApplication):
    '''Acts as wrapper for TA Instrument TRIOS application. Utilized pywinauto 
    to control the application'''
    # WINDOW_NAME =  "TA Instruments Trios" #"5333-0538 : TA Instruments Trios v5.0.0.44608"
    # PATH  = Path(r"C:\Program Files (x86)\TA Instruments\TRIOS\Trios.exe")

    def __init__(
            self,
            app: Application,
            window_name: str,
            backend:str,
            settings: Settings,
        ) -> None:
        super().__init__(app,window_name=window_name,backend=backend)

        self._settings = settings
        self.datalogger = None

        self._event_stop = threading.Event()
        self._calibrated = False
        self._zero_gap_set = False

    @classmethod
    def start(cls,window_name:str,paths:List[Union[str,Path]],backend='uia',
              settings: Settings=None, **kwargs):
        '''start application and connect
        Args:
        Returns:
            object
        Raises:
        '''
        if settings is None:
            raise ValueError('settings argument must be provided')
        obj = super().start(paths=paths,window_name=window_name,
            backend=backend,settings=settings,**kwargs)
        #Instrument view - connect to HR-3
        # gives error if Instrument view is already open
        dialog1 = obj.app.window(title="Instrument View")
        dialog1.Connect.click()
        pane1 = obj.app[window_name]['Experiment 1']
        pane1.wait("ready")     #waits till the experiment pane is ready
        #@jan: Do we need this? maybe there is some event to wait for...
        logger.info("connected to trios")

        return obj
    
    @classmethod
    def connect(cls,window_name:str,paths: List[Union[str,Path]]=None,
        start_if_not_open: bool = True,backend:str="uia",
        settings:Settings=None,**kwargs):
        '''connect to running instance of TRIOS
        '''
        if settings is None:
            raise ValueError('settings argument must be provided')
        
        return super().connect(window_name=window_name, paths=paths,
                               start_if_not_open=start_if_not_open,
                               backend=backend,settings=settings,**kwargs)
    def calibrate(self):
        '''Represent calibration process, for now asks user to press Ok when he
        has done this
        Args:
        Returns:
        Raises:
        '''

        show_warning_messagebox(message="Calibration will be performed. "
            "Please ensure the device is ready before"
            "continuing.\nPress OK when done")
        raise NotImplementedError("calibration process not implemented yet")
        self._calibrated = True

    def find_zero_gap(self,show_warning:bool=True):
        '''Represents gap zeroing process
        Args:
        Returns:
        Raises:
        '''
        if show_warning:
            show_warning_messagebox(message="Make sure that the rheometer "
                "geometry is ready for gap zeroing\n"
                "Press OK when done",title = "Advice")
        self.window_main.set_focus()
        navigation_bar = self.window_main.child_window(auto_id="navigationBarControlPanels", control_type="Pane")
        try:
            navigation_bar.wait("exists",timeout=1)
        except pywinauto.timings.TimeoutError as te:
            logger.exception("naviagation bar not found")
            raise ElementNotFoundError("could not find navigation bar, "
                                       "cannot set zero gap") from te
        zero_gap_button = navigation_bar.child_window(title="Zero Gap", control_type="Button")
        try:
            zero_gap_button.wait("exists",timeout=1)
        except pywinauto.timings.TimeoutError as te:
            logger.exception("zero gap button not found")
            raise ElementNotFoundError("could not find zero gap button, "
                                       "cannot set zero gap") from te

        zero_gap_button.click_input()
        raise NotImplementedError("Waiting for zero gap success not implemented yet")
        self._zero_gap_set = True

    def _input_experiment_names(self,experiment_info:ExperimentInfo):
        '''
        Args:
        
        Returns:
        
        Raises:'''

        sample_dropdown_button = self._get_experiment_tab_buttons("Sample: .*")[0]
        sample_dropdown_button.draw_outline()
        #sample_dropdown_button.click_input()

        # This is an example version of how we can enter the file path to be saved
        #@jan: something is missing to enter the filename?
        sample_edit = self.window_main\
            .child_window(auto_id="Link_Name_E", control_type="Edit")
        try:
            base_wrapper.BaseWrapper.verify_visible(sample_edit)
            logger.info('sample dropdown already expanded')
        except:
            sample_dropdown_button.click_input()
            logger.info('sample dropdown expanded')
        sample_edit.wait("visible",timeout=5)
        write_to_input(sample_edit,
            experiment_info.sample_name,escape_special_chars=True)
    
        operator_edit = self.window_main\
            .child_window(auto_id="Link_Operator_E", control_type="Edit")
        write_to_input(operator_edit,
            experiment_info.operator_name,escape_special_chars=True)

        file_name_ctrl = self.window_main.child_window(title="File Name:", control_type="Text")
        file_name_ctrl.draw_outline()
        file_name_ctrl.click_input()
        keyboard.send_keys("{TAB}^a"+str(experiment_info.savedir_trios))
        file_name_ctrl.click_input()

    def _read_control_panel(self)->Dict[str,Any]:
        #self.window_main.Control_panel.draw_outline()
        logger.info('reading control panel')
        val_dict = {}
        
        control_panel = self.window_main.child_window(title="Control panel", control_type="Pane")
        control_panel.exists(2)
        grid = control_panel.child_window(auto_id="RealTimeGrid", control_type="DataGrid")
        grid.exists(2)

        retries = 50
        for trial in range(retries):
            try:
                for child in grid.iter_children():
                    #child.draw_outline()
                    texts = child.texts()
                    if len(texts) < 3: continue
                    name,value,unit = texts[:3]
                    logger.debug("read control panel value: %s=%s %s", name, value, unit)
                    try:
                        val_dict[name] = float(value.replace(',','.'))
                    except ValueError:
                        val_dict[name] = value
                return val_dict

            except COMError as ce:
                logging.warning("Got COMError %s while trying to read control "
                                "panel, retrying (%d/%d)", ce, trial, retries)
                continue

        raise RuntimeError(f'COMError still persists after more than {retries} retries')

    def _get_gap_value(self):
        '''get the gap value from the controls window'''
        
        #@jan: this could be written more general to get different values from
        #the dialog but it should suffice for now

        control_values = self._read_control_panel()
        gap = control_values['Gap']
        if gap is None:
            raise ValueError('Gap not found, did you run zero gap?')
        return gap

    def _get_experiment_tab_buttons(self,tab_title_re:str):
        ''''''
        tab = self.window_main.child_window(title_re=tab_title_re, auto_id="LabelText", control_type="Text")
        tab_parent = tab.parent().parent()
        buttons = list(filter(is_button,tab_parent.children()))

        return buttons

    def _load_procedure_file(self,filepath:Path):
        ''''''
        if not filepath.is_file():
            raise FileNotFoundError(f'could not find procedure file at {filepath}')
      
        open_procedure_file_button = self._get_experiment_tab_buttons("Procedure: .*")[1]
        open_procedure_file_button.click_input()
        logger.info("waiting for procedure file dialog")
        #Desktop(backend='win32')["Open procedure"].wait('exists',5)
        Desktop(backend='win32').window(title_re ="Open procedure*").wait('exists',5)
        logger.info("typing procedure file path")
        keyboard.send_keys('^a'+str(filepath.with_suffix(''))+"{ENTER}") # type the address of procedure file 2a
        
    def _wait_for_point_countdown(self,timeout:int=900)->None:
        '''
        '''        
        countdown_pane = self.window_main.child_window(auto_id="Link_StatusPointsLeft_E")

        # To search for the Countdown pane. Need to be tested for other materials which take time for frequency sweep
        # Starts the data logger as soon as it finds the pane
        try:
            logger.info("Waiting for point countdown panel")
            countdown_pane.wait('exists',timeout)
            logger.info("There it is: point countdown panel found!!")
        except pywinauto.timings.TimeoutError as te:
            raise pywinauto.timings.TimeoutError('timeout finding time pane') from te  


    def _wait_for_time_pane(self,timeout:int=300):
        '''
        Args:
        Raises:
        Returns:'''
        
        #Defining the Countdown time pane to look for
        time_pane = self.window_main.child_window(auto_id="Link_StatusTimeLeft_E")

        # To search for the Countdown pane. Need to be tested for other materials which take time for frequency sweep
        # Starts the data logger as soon as it finds the pane
        try:
            logger.info("Waiting for countdown time panel")
            time_pane.wait('exists',timeout)
            logger.info("There it is: time panel found!!")
        except pywinauto.timings.TimeoutError as te:
            raise pywinauto.timings.TimeoutError('timeout finding time pane') from te    
     
    def get_status(self,timeout:float=60)->str:
        '''
        '''
        
        status_window = self.window_main.child_window(auto_id="labelMainStatus", control_type="Text")
        status_window.wait('exists',timeout)
        text_str = status_window.texts()[0].lower()
        if "idle" in text_str:
            return "idle"
        elif "running" in text_str:
            return "running"
        raise ValueError(f'unknown status {text_str}')


    def set_device_settings(self,device_settings:TriosDeviceSettings,timeout:float=60):
        '''
        '''
        assert device_settings.evaluated, "settings.eval has not been called"

        #updating the velocity
        self.window_main.set_focus()
        instrument_tab =self.window_main.child_window(title="Instrument", control_type="TabItem")
        instrument_tab.draw_outline()
        instrument_tab.click_input()

        options_button = self.window_main\
            .child_window(title="Options", control_type="ToolBar")\
            .child_window(title="Options", control_type="Button")
        options_button.draw_outline()
        options_button.click_input()

        settings_window = self.window_main.child_window(title="TA Instruments TRIOS", auto_id="MasterOptionsDialog", control_type="Window")
        settings_window.wait('exists',timeout)

        #press gap button
        gap_button = settings_window.child_window(title="   Gap", control_type="ListItem")
        gap_button.draw_outline()
        gap_button.click_input()

        if device_settings.velocity is not None:
            #select dropdown
            logging.info('setting velocity to %g um/s',device_settings.velocity)
            closure_profile_dropdown = settings_window.child_window(title="Closure profile", auto_id="Link_SampleCompressionMode_E", control_type="ComboBox")
            closure_profile_dropdown.draw_outline()
            closure_profile_dropdown.click_input()
            linear_profile_item = closure_profile_dropdown.child_window(title="linear", control_type="ListItem")
            linear_profile_item.wait('exists',1)
            linear_profile_item.click_input()
            velocity_edit = settings_window.child_window(title="Velocity", auto_id="Link_CompressionVelocity_E", control_type="Edit")
            write_float_to_input(velocity_edit,device_settings.velocity)

        if device_settings.fine_velocity is not None:
            logging.info('setting fine velocity to %g um/s',device_settings.fine_velocity)
            fine_velocity_edit = settings_window.child_window(title="Fine velocity", auto_id="Link_GapSetNearVelocity_E", control_type="Edit")
            fine_velocity_edit.wait('exists',1)
            write_float_to_input(fine_velocity_edit,device_settings.fine_velocity)

        ok_button = settings_window.child_window(title="OK", auto_id="okButton", control_type="Button")
        ok_button.click_input()
        logging.info('finished setting settings')

    def _type_protocol_values(self,protocol:Protocol,specimen:Specimen):
        '''
        fill in information for protocol steps
        '''

        logger.info('filling protocol step values')
        for step in protocol.steps:
            self._check_for_stop_event()

            step_ctrl = self.window_main.child_window(title=step.label,
                auto_id="LabelDisabledText", control_type="Text")
            step_top_parent =  step_ctrl.parent().parent().parent()

            step_dropdown = step_ctrl.parent().parent().children()[0]
            step_dropdown.draw_outline("blue")
            step_dropdown.click_input()

            if step.type_ == STEP_TYPE.GAP:
                
                step_gap_control = step_top_parent.descendants(title="Gap Control", control_type="Group")[0]
                step_gap_control.draw_outline("red")
                #if self._trios_workaround:
                     #HR30
                gap_edit = step_gap_control.children()[3].children()[1]
                #else:
                #    #DHR3
                #    gap_edit = next(filter(lambda e: e.automation_id() == "Link_ProcedureGapEnd_E",step_gap_control.children(control_type="Edit")))
               
                gap_edit.draw_outline()
                gap_value = step.eval(specimen=specimen)
                logger.info('step %s setting gap value %f',step.label,gap_value)
                logger.debug('write gap value %f',gap_value)
                write_float_to_input(gap_edit,gap_value)
            
            elif step.type_ == STEP_TYPE.VELOCITY:
                step_closure_control = step_top_parent.descendants(title="Closure profile", control_type="Group")[0]
              
                closure_profile_dropdown = step_closure_control.children()[1]   
                closure_profile_dropdown.draw_outline()
                closure_profile_dropdown.select("Linear")
             
                velocity_edit = step_closure_control.children()[3].children()[0]
                velocity_edit.draw_outline()
                velocity_edit.click_input()
                velocity_value = step.eval(specimen=specimen)
                write_float_to_input(velocity_edit,velocity_value)

            elif step.type_ == STEP_TYPE.WAIT_FOR_TEMPERATURE:
                step_env_control = step_top_parent.descendants(title="Environmental Control", control_type="Group")[0]
                step_env_control.draw_outline("red")
                #if self._trios_workaround:
                temp_checkbox = next(filter(lambda e: e.element_info.name ==  'Wait For Temperature',
                    step_env_control.children(control_type="CheckBox")))
                #else:
                #DHR 3
                #    temp_checkbox = next(filter(lambda e: e.automation_id() == "Link_ProcedureWaitForTemperature_E",step_env_control.children(control_type="CheckBox")))
                
                temp_checkbox.draw_outline()
                checkbox_state = temp_checkbox.get_toggle_state()
                logger.debug(f"checkbox state for {step.label}:{checkbox_state}")
                if  temp_checkbox.get_toggle_state() != 1:
                    logger.debug("toggle checkbox for %s",step.label)
                    temp_checkbox.click_input()
            elif step.type_ == STEP_TYPE.MOTOR_ROTATION:
                step_advanced = step_top_parent.descendants(title="Advanced", control_type="Group")[0]
                step_advanced_button = step_advanced.children()[0]
                step_advanced_button.draw_outline()
                step_advanced_button.click_input()
                motor_rotation_edit = step_advanced.children()[0].children()[0]
                motor_rotation_edit.draw_outline()
                motor_rotation_edit.click_input()
                motor_rotation_value = step.eval(specimen=specimen)
                logger.info('step %s superimposing motor rotation value %f',step.label,motor_rotation_value)
                write_float_to_input(motor_rotation_edit,motor_rotation_value)
            elif step.type_ == STEP_TYPE.SOAK_TIME:
                step_env_control = step_top_parent.descendants(title="Environmental Control", control_type="Group")[0]
                soak_time_block = next(
                        custon for custon in step_env_control.descendants(control_type="Custom")
                        if custon.automation_id() == "SoakTimeBlock"
                )
                soak_time_edit = soak_time_block.children(control_type="Edit")[0]
                soak_time_edit.draw_outline()
                soak_time_value = step.eval(specimen=specimen)
                logger.info('step %s setting soak time value %f',step.label,soak_time_value)
                write_float_to_input(soak_time_edit,soak_time_value)
            else:
                raise ValueError(f'step type {step.type_} unknown')

            #close dropdown
            step_dropdown.click_input()

    def _check_for_stop_event(self):
        if self._event_stop.is_set():
            self._event_stop.clear()
            raise StopException()

    def _run_protocol(self,protocol:Protocol,settings:Settings,
        specimen:Specimen,filepath_datalogger:Path):
        '''
        '''

        self.window_main.set_focus()
        self._type_protocol_values(protocol,specimen)

        self._check_for_stop_event()

        device_settings_evaluated = copy.deepcopy(settings.device_settings)
        device_settings_evaluated.eval(specimen=specimen)
        self.set_device_settings(device_settings_evaluated)

        if settings.datalogger_restart:
            self.detach_datalogger()
            time.sleep(.1)

        self._check_for_stop_event()
        if self.datalogger is None:
            self.attach_datalogger()
            timelog_file = filepath_datalogger.with_stem(
                filepath_datalogger.stem+'_timelog').with_suffix('.csv')
            self.datalogger.set_timelog_file(timelog_file)
            self.datalogger.set_path(filepath_datalogger)

        self.window_main.set_focus()

        # To start the experiment
        experiment_tab =self.window_main.child_window(title="Experiment", control_type="TabItem")
        experiment_tab.draw_outline()
        experiment_tab.click_input()

        start_button = self.window_main\
            .child_window(title="Experiment", control_type="ToolBar")\
            .child_window(title="Start", control_type="Button")
        start_button.draw_outline()
        start_button.click_input()
        #self.window_main.Start.click_input()

        #TODO: make this more flexible (when to start the datalogger)
        if not self.datalogger.is_recording:
            if protocol.has_frequency_sweep:
                self._wait_for_point_countdown()
                self._wait_for_time_pane(settings.freqsweep_timeout)
            datalogger_file_found = False
            for _ in range(10):
                self.datalogger.start_recording()
                #give the system time to create datalogger file
                time.sleep(.01)
                if self.datalogger.check_file_exists():
                    datalogger_file_found = True
                    logger.info('Found datalogger file: %s',self.datalogger.get_path())
                    break
                logger.error('Could not find datalogger file: %s',self.datalogger.get_path())

            if not datalogger_file_found:
                show_error_messagebox("datalogger file not found after 10 tries")
                raise RuntimeError(
                    f'datalogger file {self.datalogger.get_path()} not found')

            self.window_main.set_focus()

        status = self.get_status()
        while status == "running":
            time.sleep(.1)
            status = self.get_status()

        if status != "idle":
            raise ValueError(f"got status {status} but expected idle")
        
        logger.info("finished running protocol %s",repr(protocol))
            
    def run_experiment(self,experiment_info:ExperimentInfo):
        '''Run experiment
        Args:
            experiment_info: ExperimentInfo object defining the experiment
        Returns:
        Raises:
        '''

        if self.datalogger_is_open():
            raise RuntimeError("datalogger is already open, please close it"
                               " before starting the experiment")

        self.window_main.set_focus() # brings the window to top
        self._focus_experiment_tab()

        self._check_for_stop_event()
        #now run the protocol etc.
        height = self._get_gap_value()
        logger.info('found specimen height: %g',height)
        specimen = Specimen(height)

        self._check_for_stop_event()
        self._set_geometry(specimen)

        self._check_for_stop_event()
        self._input_experiment_names(experiment_info)
       
        experiment_settings = (
            copy.deepcopy(self._settings)
            .update(experiment_info.meta_protocol.settings_update)
            )

        for n,protocol in enumerate(experiment_info.meta_protocol.protocols):
            self._check_for_stop_event()
            protocol_settings = (
                copy.deepcopy(experiment_settings)
                .update(protocol.settings_update)
                )
            self._load_procedure_file(protocol.procedure_file_path)
            #TODO: find a nicer way to pass the updated datalogger save path
            filepath_datalogger_inc = experiment_info.filepath_datalogger.with_stem(
                experiment_info.filepath_datalogger.stem+f'_{n+1}')
            self._run_protocol(
                protocol,
                protocol_settings,
                specimen,
                filepath_datalogger=filepath_datalogger_inc)
            self._focus_experiment_tab()

        self._check_for_stop_event()

        #stop and kill the datalogger if it is still open
        if self.datalogger is not None:
            self.detach_datalogger()

        self._zero_gap_set = False
        self._calibrated = False

        self._check_for_stop_event()
        if self._settings.idle_velocity is not None:
            self._set_idle_velocity(self._settings.idle_velocity)

        self._check_for_stop_event()
        if self._settings.idle_gap is not None and self._settings.idle_gap != SETTING_VALUE_NOT_SET :
            self.set_gap(self._settings.idle_gap)

    def set_gap(self,gap:float,ask_confirmation:bool=True):
        if gap < 0:
            raise ValueError('gap cannot be negative')
        
        if ask_confirmation and not show_yesno_messagebox(
            f"Should the gap be set to {gap} um?"):
            return

        self.window_main.set_focus()

        set_gap_edit = self.window_main.child_window(auto_id="LinkControlSetGap_E", control_type="Edit")
        wait_until_element_exists(set_gap_edit,timeout=1)
        set_gap_edit.draw_outline()
        write_float_to_input(set_gap_edit,gap)
        set_gap_button = self.window_main.child_window(auto_id="LinkControlSetGap_U", control_type="Button")
        wait_until_element_exists(set_gap_button,timeout=1)
        set_gap_button.draw_outline()
        set_gap_button.click_input()

    def stop_experiment(self)->None:
        self._event_stop.set()

    def _set_idle_velocity(self,velocity:float):

        self.set_device_settings(
            TriosDeviceSettings(velocity=velocity,fine_velocity=velocity))


    def attach_datalogger(self):
        ''''''
        self.datalogger = DataLogger.connect(
            window_name=self._settings.datalogger_windowname,
            paths=self._settings.datalogger_paths,
            start_if_not_open=True
        )

    def datalogger_is_open(self)->bool:
        ''''''
        return DataLogger.is_open(
            window_name=self._settings.datalogger_windowname,
            paths=self._settings.datalogger_paths)

    def detach_datalogger(self):
        if self.datalogger is not None:
            self.datalogger.stop_recording()
            self.datalogger.exit()
            self.datalogger = None


    def _set_geometry(self,specimen):
        ''''''
        # Enters the gap value in Geometry dropdown section
        #self.window_main.Button5.click_input()
        
        gap_edit = self.window_main.child_window(auto_id="Link_Gap_E",control_type="Edit")
        try:
            gap_edit.wait("visible",1)
        except pywinauto.timings.TimeoutError:
            geometry_dropdown_button = self._get_experiment_tab_buttons("Geometry: .*")[0]
            geometry_dropdown_button.draw_outline()
            geometry_dropdown_button.click_input()
        gap_edit.wait("visible",1)
        gap_edit.draw_outline()
        write_float_to_input(gap_edit,specimen.height)

    def _focus_experiment_tab(self)->None:
        '''
        '''
        self.window_main.child_window(title="Experiment", control_type="TabItem").draw_outline()#.click_input()
        #self.window_main.child_window(title="Instrument", control_type="TabItem").click_input()
        self.window_main.child_window(title="Experiment", control_type="TabItem").click_input()
        self.window_main.child_window(title="Geometry", control_type="ToolBar").child_window(title="Calibrate", control_type="Button").draw_outline()#click()
        self.window_main.child_window(title="Geometry", control_type="ToolBar").child_window(title="Calibrate", control_type="Button").click()
        self.window_main.child_window(title="Procedure", control_type="ToolBar").child_window(title="Setup", control_type="Button").draw_outline()#click()
        self.window_main.child_window(title="Procedure", control_type="ToolBar").child_window(title="Setup", control_type="Button").click()

