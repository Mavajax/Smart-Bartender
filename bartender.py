import gaugette.ssd1306
import gaugette.platform
import gaugette.gpio
import time
import sys
import RPi.GPIO as GPIO
import json
import traceback

from lib_oled96 import ssd1306
from smbus import SMBus
from PIL import ImageFont, ImageDraw, Image
FONT = ImageFont.truetype("FreeMono.ttf", 15)
I2CBUS = SMBus(1)

from dotstar import Adafruit_DotStar
from menu import MenuItem, Menu, Back, MenuContext, MenuDelegate
from drinks import drink_list, drink_options

GPIO.setmode(GPIO.BCM)

SCREEN_WIDTH = 128
SCREEN_HEIGHT = 64

LEFT_BTN_PIN = 13
LEFT_PIN_BOUNCE = 600

RIGHT_BTN_PIN = 5
RIGHT_PIN_BOUNCE = 600

OLED_RESET_PIN = 15
OLED_DC_PIN = 16

FLOW_RATE = 60.0/100.0

class Bartender(MenuDelegate): 
	def __init__(self):
		self.running = False

		# set the oled screen height
		self.screen_width = SCREEN_WIDTH
		self.screen_height = SCREEN_HEIGHT

		self.btn1Pin = LEFT_BTN_PIN
		self.btn2Pin = RIGHT_BTN_PIN

		# configure interrups for buttons
		GPIO.setup(self.btn1Pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.setup(self.btn2Pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)  

		# Very important... This lets py-gaugette 'know' what pins to use in order to reset the display
		self.led = ssd1306(I2CBUS) # Change rows & cols values depending on your display dimensions.
		logo = Image.open('pi_logo.png')
		self.led.canvas.bitmap((32, 0), logo, fill=0)
		self.led.display()

		# load the pump configuration from file
		self.pump_configuration = Bartender.readPumpConfiguration()
		for pump in self.pump_configuration.keys():
			GPIO.setup(self.pump_configuration[pump]["pin"], GPIO.OUT, initial=GPIO.HIGH)

		print "Done initializing"

	@staticmethod
	def readPumpConfiguration():
		return json.load(open('pump_config.json'))

	@staticmethod
	def writePumpConfiguration(configuration):
		with open("pump_config.json", "w") as jsonFile:
			json.dump(configuration, jsonFile)

	def startInterrupts(self):
		self.running = True
		GPIO.add_event_detect(self.btn1Pin, GPIO.FALLING, callback=self.left_btn, bouncetime=LEFT_PIN_BOUNCE)  
		GPIO.add_event_detect(self.btn2Pin, GPIO.FALLING, callback=self.right_btn, bouncetime=RIGHT_PIN_BOUNCE)
		time.sleep(1)
		self.running = False

	def buildMenu(self, drink_list, drink_options):
		# create a new main menu
		m = Menu("Main Menu")

		# add drink options
		drink_opts = []
		for d in drink_list:
			drink_opts.append(MenuItem('drink', d["name"], {"ingredients": d["ingredients"]}))

		configuration_menu = Menu("Configure")

		# add pump configuration options
		pump_opts = []
		for p in sorted(self.pump_configuration.keys()):
			config = Menu(self.pump_configuration[p]["name"])
			# add fluid options for each pump
			for opt in drink_options:
				# star the selected option
				selected = "*" if opt["value"] == self.pump_configuration[p]["value"] else ""
				config.addOption(MenuItem('pump_selection', opt["name"], {"key": p, "value": opt["value"], "name": opt["name"]}))
			# add a back button so the user can return without modifying
			config.addOption(Back("Back"))
			config.setParent(configuration_menu)
			pump_opts.append(config)

		# add pump menus to the configuration menu
		configuration_menu.addOptions(pump_opts)
		# add a back button to the configuration menu
		configuration_menu.addOption(Back("Back"))
		# adds an option that cleans all pumps to the configuration menu
		configuration_menu.addOption(MenuItem('clean', 'Clean'))
		configuration_menu.setParent(m)

		m.addOptions(drink_opts)
		m.addOption(configuration_menu)
		# create a menu context
		self.menuContext = MenuContext(m, self)

	def filterDrinks(self, menu):
		"""
		Removes any drinks that can't be handled by the pump configuration
		"""
		for i in menu.options:
			if (i.type == "drink"):
				i.visible = False
				ingredients = i.attributes["ingredients"]
				presentIng = 0
				for ing in ingredients.keys():
					for p in self.pump_configuration.keys():
						if (ing == self.pump_configuration[p]["value"]):
							presentIng += 1
				if (presentIng == len(ingredients.keys())):
					i.visible = True
			elif (i.type == "menu"):
				self.filterDrinks(i)

	def selectConfigurations(self, menu):
		"""
		Adds a selection star to the pump configuration option
		"""
		for i in menu.options:
			if (i.type == "pump_selection"):
				key = i.attributes["key"]
				if (self.pump_configuration[key]["value"] == i.attributes["value"]):
					i.name = "%s %s" % (i.attributes["name"], "*")
				else:
					i.name = i.attributes["name"]
			elif (i.type == "menu"):
				self.selectConfigurations(i)

	def prepareForRender(self, menu):
		self.filterDrinks(menu)
		self.selectConfigurations(menu)
		return True

	def menuItemClicked(self, menuItem):
		if (menuItem.type == "drink"):
			self.makeDrink(menuItem.name, menuItem.attributes["ingredients"])
			return True
		elif(menuItem.type == "pump_selection"):
			self.pump_configuration[menuItem.attributes["key"]]["value"] = menuItem.attributes["value"]
			Bartender.writePumpConfiguration(self.pump_configuration)
			return True
		elif(menuItem.type == "clean"):
			self.clean()
			return True
		return False

	def clean(self):
		pins = []

		for pump in self.pump_configuration.keys():
			pins.append(self.pump_configuration[pump]["pin"])

		self.startProgressBar()
		GPIO.output(pins, GPIO.LOW)
		self.sleepAndProgress(time.time(),20,20)
		GPIO.output(pins, GPIO.HIGH)

		# show the main menu
		self.menuContext.showMenu()

		# sleep for a couple seconds to make sure the interrupts don't get triggered
		time.sleep(2);

	def displayMenuItem(self, menuItem):
		print menuItem.name
		self.led.cls()
		self.led.canvas.text((0,20),menuItem.name, font=FONT, fill=1)
		self.led.display()

	def pour(self, pin, waitTime):
		GPIO.output(pin, GPIO.LOW)
		time.sleep(waitTime)
		GPIO.output(pin, GPIO.HIGH)

	def startProgressBar(self,x=15,y=20):
		start_time = time.time()
		self.led.cls()
		self.led.canvas.text((10,20),"Dispensing...", font=FONT, fill=1)

	def sleepAndProgress(self, startTime, waitTime, totalTime, x=15, y=35):
		localStartTime = time.time()
		height = 10
		width = self.screen_width-2*x

		while time.time() - localStartTime < waitTime:
			progress = (time.time() - startTime)/totalTime
			p_loc = int(progress*width)
			self.led.canvas.rectangle((x,y,x+width,y+height), outline=255, fill=0)
			self.led.canvas.rectangle((x+1,y+1,x+p_loc,y+height-1), outline=255, fill=1)
			try:
				self.led.display()
			except IOError:
				print("Failed to talk to screen")
			time.sleep(0.2)

	def makeDrink(self, drink, ingredients):
		# cancel any button presses while the drink is being made
		self.running = True

		# Parse the drink ingredients and create pouring data
		pumpTimes = []
		for ing in ingredients.keys():
			for pump in self.pump_configuration.keys():
				if ing == self.pump_configuration[pump]["value"]:
					waitTime = ingredients[ing] * FLOW_RATE
					pumpTimes.append([self.pump_configuration[pump]["pin"], waitTime])

		# Put the drinkjs in the order they'll stop pouring
		pumpTimes.sort(key=lambda x: x[1])

		# Note the total time required to pour the drink
		totalTime = pumpTimes[-1][1]

		# Change the times to be relative to the previous not absolute
		for i in range(1,len(pumpTimes)):
			pumpTimes[i][1] -= pumpTimes[i-1][1]

		print(pumpTimes)

		self.startProgressBar()
		startTime = time.time()
		print("starting all")
		GPIO.output([p[0] for p in pumpTimes], GPIO.LOW)
		for p in pumpTimes:
			pin, delay = p
			if delay > 0: 
				self.sleepAndProgress(startTime, delay, totalTime)
			GPIO.output(pin, GPIO.HIGH)
			print("stopping {}".format(pin))

		# show the main menu
		self.menuContext.showMenu()

		# sleep for a couple seconds to make sure the interrupts don't get triggered
		time.sleep(2)


	def left_btn(self, ctx):
		print("LEFT_BTN pressed")
		if not self.running:
			self.running = True
			self.menuContext.advance()
			print("Finished processing button press")
		self.running = False

	def right_btn(self, ctx):
		print("RIGHT_BTN pressed")
		if not self.running:
			self.running = True
			self.menuContext.select()
			print("Finished processing button press")
			self.running = 2
			print("Starting button timeout")

	def run(self):
		self.startInterrupts()
		# main loop
		try:
			try:
				while True:
					letter = raw_input(">")
					if letter == "l":
						self.left_btn(False)
					if letter == "r":
						self.right_btn(False)
			except EOFError:
				while True:
					time.sleep(0.1)
					if self.running not in (True,False):
						self.running -= 0.1
						if self.running == 0:
							self.running = False
							print("Finished button timeout")

		except KeyboardInterrupt:
			GPIO.cleanup()       # clean up GPIO on CTRL+C exit
		finally:
			GPIO.cleanup()       # clean up GPIO on normal exit

		traceback.print_exc()


bartender = Bartender()
bartender.buildMenu(drink_list, drink_options)
bartender.run()




